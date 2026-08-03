"""Opsora resilience layer — structured logging, timeouts, retry, circuit breakers.

Phase 1 (tasks 16-18). Stdlib-only; no network and no heavy imports at module
import time so it is safe to load from tests and from ``opsora_v2`` early boot.

Components
----------
1. **Structured logging with correlation ids** — JSON-line records
   (``ts``, ``level``, ``correlation_id``, ``event``, details) written to a
   rotating file (default ``$OPSORA_WORKSPACE_ROOT/.opsora/logs/opsora.log``)
   or, when ``OPSORA_LOG_FILE=stderr|stdout``, to the respective stream.
   ``OPSORA_LOG_FILE=off`` disables logging. A file is the default sink
   because the Rich ``Live`` spinner owns the terminal — JSON lines on
   stderr would visually interleave with the TUI. Every record is redacted
   with the same rules as the console output (``opsora_tui.redact_display``
   when importable, built-in fallback otherwise): secrets never reach logs.

2. **Timeout/retry configuration** — ``config/resilience.json`` (repo root)
   holds defaults; environment variables override the file. The provider
   getters in ``opsora_v2`` read ``timeout_seconds`` from here instead of a
   hardcoded constant.

3. **Retry with exponential backoff + jitter** — ``retry_with_backoff`` wraps
   the provider call choke point. Only *transient* errors (5xx, 429,
   connection/timeout errors) are retried; 4xx auth/validation errors raise
   immediately.

4. **Circuit breaker** — one ``CircuitBreaker`` per provider (in-memory,
   thread-safe). After ``failure_threshold`` consecutive failed operations
   the breaker opens and fails fast for ``cooldown_seconds``; it then moves
   to half-open and admits a single probe call whose outcome decides whether
   the breaker closes or re-opens. Only transient errors count toward the
   threshold — a bad model name (404) or invalid key (401) must not suppress
   an otherwise healthy provider.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import random
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError

__all__ = [
    "CircuitBreaker",
    "CircuitOpenError",
    "ResilienceConfig",
    "StructuredLogger",
    "all_breaker_status",
    "get_breaker",
    "get_config",
    "get_correlation_id",
    "get_logger",
    "is_transient_error",
    "new_turn_correlation_id",
    "reload_config",
    "reset_breakers",
    "reset_config_cache",
    "reset_logger",
    "retry_with_backoff",
    "set_correlation_id",
]


# ============================================================================
# Configuration (task 17)
# ============================================================================

# Repo-root config file, same pattern as opsora_cost.CONFIG_PATH — tests may
# monkeypatch this.
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "resilience.json"

# Built-in defaults mirror config/resilience.json so behavior is unchanged
# when the file is missing or malformed.
_BUILTIN_DEFAULTS: dict[str, Any] = {
    # Provider HTTP timeout (seconds). Matches the legacy DEFAULT_TIMEOUT=40
    # previously hardcoded in opsora_v2.
    "timeout_seconds": 40,
    # The self-hosted Opsora API gateway runs slower models; legacy value 120.
    "opsora_api_timeout_seconds": 120,
    "retry": {
        # Total attempts per provider call (1 initial + 2 retries).
        "max_attempts": 3,
        "base_delay_seconds": 0.5,
        "max_delay_seconds": 8.0,
        # +/-25% randomized jitter to avoid thundering-herd retries.
        "jitter_ratio": 0.25,
    },
    "circuit_breaker": {
        "failure_threshold": 5,
        "cooldown_seconds": 60.0,
    },
}


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    jitter_ratio: float = 0.25


@dataclass
class BreakerPolicy:
    failure_threshold: int = 5
    cooldown_seconds: float = 60.0


@dataclass
class ResilienceConfig:
    timeout_seconds: float = 40
    opsora_api_timeout_seconds: float = 120
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    circuit_breaker: BreakerPolicy = field(default_factory=BreakerPolicy)


def _coerce_num(value: Any, fallback: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return fallback
    return num if num > 0 else fallback


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        num = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return num if num >= 1 else fallback


def _deep_get(raw: dict, *keys: str) -> Any:
    node: Any = raw
    for k in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(k)
    return node


def load_config(path: Optional[Path] = None) -> ResilienceConfig:
    """Build a :class:`ResilienceConfig` from built-in defaults, then the JSON
    file at ``path`` (default :data:`CONFIG_PATH`), then env overrides.

    Never raises on missing/malformed configuration — falls back to the
    built-in defaults so a bad config file can never break the CLI.
    """
    cfg = ResilienceConfig(
        timeout_seconds=_BUILTIN_DEFAULTS["timeout_seconds"],
        opsora_api_timeout_seconds=_BUILTIN_DEFAULTS["opsora_api_timeout_seconds"],
        retry=RetryPolicy(**_BUILTIN_DEFAULTS["retry"]),
        circuit_breaker=BreakerPolicy(**_BUILTIN_DEFAULTS["circuit_breaker"]),
    )

    target = Path(path) if path is not None else CONFIG_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.timeout_seconds = _coerce_num(
                raw.get("timeout_seconds", cfg.timeout_seconds), cfg.timeout_seconds)
            cfg.opsora_api_timeout_seconds = _coerce_num(
                raw.get("opsora_api_timeout_seconds", cfg.opsora_api_timeout_seconds),
                cfg.opsora_api_timeout_seconds)
            for attr in ("max_attempts",):
                val = _deep_get(raw, "retry", attr)
                if val is not None:
                    setattr(cfg.retry, attr, _coerce_int(val, getattr(cfg.retry, attr)))
            for attr in ("base_delay_seconds", "max_delay_seconds", "jitter_ratio"):
                val = _deep_get(raw, "retry", attr)
                if val is not None:
                    setattr(cfg.retry, attr, _coerce_num(val, getattr(cfg.retry, attr)))
            cfg.circuit_breaker.failure_threshold = _coerce_int(
                _deep_get(raw, "circuit_breaker", "failure_threshold"),
                cfg.circuit_breaker.failure_threshold)
            cfg.circuit_breaker.cooldown_seconds = _coerce_num(
                _deep_get(raw, "circuit_breaker", "cooldown_seconds"),
                cfg.circuit_breaker.cooldown_seconds)
    except (OSError, ValueError):
        pass  # Missing/unreadable/malformed file → keep built-in defaults.

    # Environment overrides win over the file (highest precedence).
    env = os.environ
    cfg.timeout_seconds = _coerce_num(env.get("OPSORA_TIMEOUT"), cfg.timeout_seconds)
    cfg.opsora_api_timeout_seconds = _coerce_num(
        env.get("OPSORA_API_TIMEOUT"), cfg.opsora_api_timeout_seconds)
    cfg.retry.max_attempts = _coerce_int(
        env.get("OPSORA_RETRY_MAX_ATTEMPTS"), cfg.retry.max_attempts)
    cfg.circuit_breaker.failure_threshold = _coerce_int(
        env.get("OPSORA_BREAKER_THRESHOLD"), cfg.circuit_breaker.failure_threshold)
    cfg.circuit_breaker.cooldown_seconds = _coerce_num(
        env.get("OPSORA_BREAKER_COOLDOWN"), cfg.circuit_breaker.cooldown_seconds)
    return cfg


_config_cache: Optional[ResilienceConfig] = None
_config_lock = threading.Lock()


def get_config() -> ResilienceConfig:
    """Return the cached config.

    The file portion is loaded once; environment overrides are re-applied on
    every call so tests (and live env changes) take effect without restarts.
    """
    global _config_cache
    with _config_lock:
        if _config_cache is None:
            _config_cache = load_config()
        # Re-apply env overrides live so monkeypatched/changed env vars take
        # effect without a reload.
        return _apply_env(_config_cache)


def _apply_env(cfg: ResilienceConfig) -> ResilienceConfig:
    """Return a copy of *cfg* with environment overrides applied."""
    env = os.environ
    out = ResilienceConfig(
        timeout_seconds=_coerce_num(env.get("OPSORA_TIMEOUT"), cfg.timeout_seconds),
        opsora_api_timeout_seconds=_coerce_num(
            env.get("OPSORA_API_TIMEOUT"), cfg.opsora_api_timeout_seconds),
        retry=RetryPolicy(
            max_attempts=_coerce_int(env.get("OPSORA_RETRY_MAX_ATTEMPTS"), cfg.retry.max_attempts),
            base_delay_seconds=cfg.retry.base_delay_seconds,
            max_delay_seconds=cfg.retry.max_delay_seconds,
            jitter_ratio=cfg.retry.jitter_ratio,
        ),
        circuit_breaker=BreakerPolicy(
            failure_threshold=_coerce_int(
                env.get("OPSORA_BREAKER_THRESHOLD"), cfg.circuit_breaker.failure_threshold),
            cooldown_seconds=_coerce_num(
                env.get("OPSORA_BREAKER_COOLDOWN"), cfg.circuit_breaker.cooldown_seconds),
        ),
    )
    return out


def reload_config(path: Optional[Path] = None) -> ResilienceConfig:
    """Force a full reload from disk + env (used by tests and diagnostics)."""
    global _config_cache
    with _config_lock:
        _config_cache = load_config(path)
        return _apply_env(_config_cache)


def reset_config_cache() -> None:
    """Drop the cached config so the next get_config() reloads (test hook)."""
    global _config_cache
    with _config_lock:
        _config_cache = None


# ============================================================================
# Transient-error classification (task 17)
# ============================================================================

_HTTP_CODE_IN_MSG = re.compile(r"\bHTTP\s+(\d{3})\b", re.I)
_TRANSIENT_CLASS_NAMES = {
    # openai >= 1.x SDK names (matched by class name so we don't require the
    # package at import time — this CLI also ships an urllib-based fallback
    # client, openai_lite, when the SDK is unavailable).
    "APITimeoutError", "APIConnectionError", "RateLimitError",
    "InternalServerError", "BadGatewayError", "ServiceUnavailableError",
    "GatewayTimeoutError", "Timeout", "ConnectTimeout", "ReadTimeout",
}


def _status_from_cause_chain(exc: BaseException, depth: int = 3) -> Optional[int]:
    """Walk ``__cause__``/``__context__`` looking for an HTTP status code."""
    current: Optional[BaseException] = exc
    seen = 0
    while current is not None and seen < depth:
        if isinstance(current, HTTPError) and isinstance(getattr(current, "code", None), int):
            return current.code
        status = getattr(current, "status_code", None)
        if isinstance(status, int):
            return status
        current = current.__cause__ or current.__context__
        seen += 1
    return None


def is_transient_error(exc: BaseException) -> bool:
    """Return True when *exc* looks like a transient provider failure.

    Transient: HTTP 5xx, 429 (rate limit), connection resets, DNS failures,
    timeouts. Fatal (never retried, never trips the breaker): 4xx auth /
    validation / not-found errors, programming errors, and the internal
    "provider not available" condition.
    """
    if exc is None:
        return False

    # Direct HTTP status attributes (openai SDK APIStatusError, requests, ...).
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
    if isinstance(status, int):
        return status >= 500 or status == 429

    # urllib shapes.
    if isinstance(exc, HTTPError) and isinstance(exc.code, int):
        return exc.code >= 500 or exc.code == 429
    if isinstance(exc, (URLError, ConnectionError, TimeoutError)):
        return True
    # socket.timeout is an alias of TimeoutError on 3.10+; keep the name check
    # for exotic builds.
    if type(exc).__name__ in _TRANSIENT_CLASS_NAMES:
        return True

    # openai_lite wraps urllib errors as RuntimeError("HTTP 503: ...") /
    # RuntimeError("Connection error: ...") with the original chained.
    chained = _status_from_cause_chain(exc)
    if chained is not None:
        return chained >= 500 or chained == 429
    msg = str(exc)
    m = _HTTP_CODE_IN_MSG.search(msg)
    if m:
        code = int(m.group(1))
        return code >= 500 or code == 429
    if "connection error" in msg.lower() or "timed out" in msg.lower() or "timeout" in msg.lower():
        return True

    # Generic OSError covers socket-level failures raised by urllib/httpx.
    if isinstance(exc, OSError):
        return True

    return False


# ============================================================================
# Retry with exponential backoff + jitter (task 17)
# ============================================================================

def retry_with_backoff(
    fn: Callable[[], Any],
    *,
    max_attempts: Optional[int] = None,
    base_delay: Optional[float] = None,
    max_delay: Optional[float] = None,
    jitter: Optional[float] = None,
    sleep: Optional[Callable[[float], None]] = None,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
) -> Any:
    """Call *fn*, retrying transient failures with exponential backoff.

    ``max_attempts`` is the TOTAL number of attempts (1 = no retry). Only
    errors classified transient by :func:`is_transient_error` are retried —
    fatal errors (4xx auth/validation, programming errors) propagate on the
    first occurrence. ``sleep`` defaults to ``time.sleep`` resolved at call
    time so tests can patch ``opsora_resilience.time.sleep``.
    """
    policy = get_config().retry
    attempts = max_attempts if max_attempts is not None else policy.max_attempts
    base = base_delay if base_delay is not None else policy.base_delay_seconds
    cap = max_delay if max_delay is not None else policy.max_delay_seconds
    jit = jitter if jitter is not None else policy.jitter_ratio
    do_sleep = sleep if sleep is not None else time.sleep

    attempts = max(1, int(attempts))
    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — classified below
            last_exc = exc
            if not is_transient_error(exc) or attempt >= attempts:
                raise
            delay = min(base * (2 ** (attempt - 1)), cap)
            if jit > 0:
                delay *= 1.0 + random.uniform(-jit, jit)
            delay = max(0.0, delay)
            if on_retry is not None:
                try:
                    on_retry(attempt, exc, delay)
                except Exception:  # noqa: BLE001 — logging must never break calls
                    pass
            do_sleep(delay)
    # Unreachable: the loop returns or raises.
    raise last_exc  # type: ignore[misc]


# ============================================================================
# Circuit breaker (task 18)
# ============================================================================

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half-open"


class CircuitOpenError(RuntimeError):
    """Raised when a provider call is rejected because its breaker is open."""

    def __init__(self, provider: str, retry_after: float = 0.0):
        self.provider = provider
        self.retry_after = retry_after
        super().__init__(
            f"Provider '{provider}' circuit breaker is open — failing fast "
            f"(retry in ~{retry_after:.0f}s)"
        )


class CircuitBreaker:
    """Per-provider circuit breaker (in-memory, thread-safe).

    States: ``closed`` (normal) → ``open`` after ``failure_threshold``
    consecutive failures (calls rejected immediately) → ``half-open`` once
    ``cooldown_seconds`` elapsed (exactly one probe call admitted) → back to
    ``closed`` on probe success, or ``open`` again on probe failure.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.name = name
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._state = CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False
        # Diagnostics counters (monotonic, never reset by state transitions).
        self.total_successes = 0
        self.total_failures = 0
        self.total_rejected = 0

    # -- state queries ------------------------------------------------------

    @property
    def state(self) -> str:
        with self._lock:
            return self._state_unlocked()

    def _state_unlocked(self) -> str:
        if self._state == OPEN and self._cooldown_elapsed_unlocked():
            return HALF_OPEN
        return self._state

    def _cooldown_elapsed_unlocked(self) -> bool:
        return (self._clock() - self._opened_at) >= self.cooldown_seconds

    def status(self) -> dict[str, Any]:
        """Snapshot for diagnostics (/status, dashboards, tests)."""
        with self._lock:
            retry_after = max(
                0.0, self.cooldown_seconds - (self._clock() - self._opened_at)
            ) if self._state == OPEN else 0.0
            return {
                "provider": self.name,
                "state": self._state_unlocked(),
                "consecutive_failures": self._consecutive_failures,
                "failure_threshold": self.failure_threshold,
                "cooldown_seconds": self.cooldown_seconds,
                "retry_after_seconds": round(retry_after, 1),
                "total_successes": self.total_successes,
                "total_failures": self.total_failures,
                "total_rejected": self.total_rejected,
            }

    # -- call gating ---------------------------------------------------------

    def allow_request(self) -> bool:
        """Return True if a call may proceed; False means fail fast."""
        with self._lock:
            state = self._state_unlocked()
            if state == CLOSED:
                return True
            if state == HALF_OPEN:
                if self._probe_in_flight:
                    # Only one probe at a time; others fail fast.
                    self.total_rejected += 1
                    return False
                self._probe_in_flight = True
                return True
            # OPEN
            self.total_rejected += 1
            return False

    def record_success(self) -> None:
        with self._lock:
            self.total_successes += 1
            self._consecutive_failures = 0
            self._probe_in_flight = False
            self._state = CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self.total_failures += 1
            was_probe = self._probe_in_flight or self._state_unlocked() == HALF_OPEN
            self._probe_in_flight = False
            self._consecutive_failures += 1
            if was_probe or self._consecutive_failures >= self.failure_threshold:
                self._state = OPEN
                self._opened_at = self._clock()
                if not was_probe:
                    # Threshold trip: counter stays so status() shows why.
                    pass
                else:
                    # Failed probe: keep the failure count at/above threshold
                    # so the breaker stays visibly unhealthy.
                    self._consecutive_failures = max(
                        self._consecutive_failures, self.failure_threshold)

    def reset(self) -> None:
        with self._lock:
            self._state = CLOSED
            self._consecutive_failures = 0
            self._probe_in_flight = False


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_breaker(provider: str) -> CircuitBreaker:
    """Return (creating if needed) the breaker for *provider*."""
    with _breakers_lock:
        breaker = _breakers.get(provider)
        if breaker is None:
            policy = get_config().circuit_breaker
            breaker = CircuitBreaker(
                provider,
                failure_threshold=policy.failure_threshold,
                cooldown_seconds=policy.cooldown_seconds,
            )
            _breakers[provider] = breaker
        return breaker


def reset_breakers() -> None:
    """Clear all breaker state (test isolation / manual recovery)."""
    with _breakers_lock:
        _breakers.clear()


def all_breaker_status() -> dict[str, dict[str, Any]]:
    """Status snapshot for every provider breaker seen so far."""
    with _breakers_lock:
        return {name: breaker.status() for name, breaker in sorted(_breakers.items())}


# ============================================================================
# Structured logging with correlation ids (task 16)
# ============================================================================

_correlation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "opsora_correlation_id", default=None
)


def new_turn_correlation_id() -> str:
    """Start a new correlation scope (one UUID per turn/request)."""
    cid = uuid.uuid4().hex
    _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: Optional[str]) -> None:
    _correlation_id.set(cid)


def get_correlation_id() -> Optional[str]:
    return _correlation_id.get()


def get_or_new_correlation_id() -> str:
    """Current correlation id, or a fresh one if none is active (e.g. calls
    made from worker threads outside a turn scope)."""
    cid = _correlation_id.get()
    if cid is None:
        cid = uuid.uuid4().hex
        _correlation_id.set(cid)
    return cid


# --- redaction ---------------------------------------------------------------

_FALLBACK_SECRET_PATTERNS = [
    re.compile(r"(nvapi-)[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(sk-(?:[A-Za-z]{2,8}-)?)[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(xai-)[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(gh[pousr]_)[A-Za-z0-9_]{16,}"),
    re.compile(r"(AIza)[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(LTAI)[0-9A-Za-z]{12,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-./+]{16,}={0,2}", re.I),
    re.compile(
        r'(["\']?(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token'
        r'|password|credential|authorization|token|secret)["\']?\s*[=:]\s*["\']?)'
        r'([A-Za-z0-9_\-/.+]{16,})',
        re.I,
    ),
]

_redact_fn: Optional[Callable[[str], str]] = None
_redact_lock = threading.Lock()


def _fallback_redact(text: str) -> str:
    for i, pattern in enumerate(_FALLBACK_SECRET_PATTERNS):
        if i == len(_FALLBACK_SECRET_PATTERNS) - 1:
            text = pattern.sub(lambda m: m.group(1) + m.group(2)[:4] + "****", text)
        else:
            text = pattern.sub(lambda m: m.group(1) + "****", text)
    return text


def redact(text: str) -> str:
    """Mask secrets in *text* before it is written to the log.

    Reuses ``opsora_tui.redact_display`` (single source of truth for console
    redaction) when importable; falls back to an equivalent built-in pattern
    set so this module never hard-depends on the TUI stack.
    """
    global _redact_fn
    if not text:
        return text
    with _redact_lock:
        if _redact_fn is None:
            try:
                from opsora_tui import redact_display  # noqa: PLC0415

                _redact_fn = redact_display
            except Exception:  # noqa: BLE001 — keep logging alive regardless
                _redact_fn = _fallback_redact
    try:
        return _redact_fn(text)
    except Exception:  # noqa: BLE001
        return _fallback_redact(text)


# --- logger -------------------------------------------------------------------

_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING,
           "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "correlation_id": getattr(record, "correlation_id", None),
            "event": record.getMessage(),
        }
        details = getattr(record, "details", None)
        if details:
            payload.update(details)
        # Redact the fully-serialized line so nested values are covered too.
        return redact(json.dumps(payload, ensure_ascii=False, default=str))


class StructuredLogger:
    """Thin JSON-line logger keyed by correlation id.

    Never raises: logging failures are swallowed so telemetry can never break
    a provider call or a turn.
    """

    def __init__(self, sink: Optional[str] = None, level: str = "INFO",
                 name: str = "opsora"):
        self._logger = logging.getLogger(f"{name}.{uuid.uuid4().hex[:8]}")
        self._logger.setLevel(_LEVELS.get(level.upper(), logging.INFO))
        self._logger.propagate = False
        self._sink = sink
        self._configure_sink(sink)

    def _configure_sink(self, sink: Optional[str]) -> None:
        for handler in list(self._logger.handlers):
            self._logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass

        if sink is None:
            sink = default_log_path()
        sink_norm = str(sink).strip().lower()
        try:
            if sink_norm in ("off", "none", "disabled", "null"):
                self._logger.addHandler(logging.NullHandler())
                self._sink_effective = "off"
                return
            if sink_norm == "stderr":
                import sys
                handler: logging.Handler = logging.StreamHandler(sys.stderr)
                self._sink_effective = "stderr"
            elif sink_norm == "stdout":
                import sys
                handler = logging.StreamHandler(sys.stdout)
                self._sink_effective = "stdout"
            else:
                path = Path(sink).expanduser()
                path.parent.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(
                    path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
                self._sink_effective = str(path)
        except (OSError, ValueError):
            self._logger.addHandler(logging.NullHandler())
            self._sink_effective = "off"
            return
        handler.setFormatter(_JsonFormatter())
        self._logger.addHandler(handler)

    @property
    def sink(self) -> str:
        return getattr(self, "_sink_effective", "off")

    def log(self, level: str, event: str, **details: Any) -> None:
        try:
            record_level = _LEVELS.get(level.upper(), logging.INFO)
            if record_level < self._logger.level:
                return
            extra = {"correlation_id": get_or_new_correlation_id(), "details": details}
            self._logger.log(record_level, event, extra=extra)
        except Exception:  # noqa: BLE001 — logging must never raise
            pass

    def debug(self, event: str, **details: Any) -> None:
        self.log("DEBUG", event, **details)

    def info(self, event: str, **details: Any) -> None:
        self.log("INFO", event, **details)

    def warning(self, event: str, **details: Any) -> None:
        self.log("WARNING", event, **details)

    def error(self, event: str, **details: Any) -> None:
        self.log("ERROR", event, **details)


def default_log_path() -> str:
    root = Path(os.environ.get("OPSORA_WORKSPACE_ROOT", "/root"))
    return str(root / ".opsora" / "logs" / "opsora.log")


_logger: Optional[StructuredLogger] = None
_logger_lock = threading.Lock()


def _logger_sink_from_env() -> Optional[str]:
    return os.environ.get("OPSORA_LOG_FILE")  # None → default file path


def get_logger() -> StructuredLogger:
    """Process-wide structured logger (created on first use).

    Configure via env: ``OPSORA_LOG_FILE`` (path | stderr | stdout | off)
    and ``OPSORA_LOG_LEVEL`` (default INFO).
    """
    global _logger
    with _logger_lock:
        if _logger is None:
            _logger = StructuredLogger(
                sink=_logger_sink_from_env(),
                level=os.environ.get("OPSORA_LOG_LEVEL", "INFO"),
            )
        return _logger


def reset_logger() -> None:
    """Drop the process-wide logger so env changes apply (test hook)."""
    global _logger
    with _logger_lock:
        if _logger is not None:
            for handler in list(_logger._logger.handlers):
                try:
                    handler.close()
                except Exception:  # noqa: BLE001
                    pass
        _logger = None
