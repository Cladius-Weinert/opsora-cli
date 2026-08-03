"""Tests for the provider resilience layer (opsora_resilience module).

Covers: config layering (built-in → file → env), transient-error
classification, retry with backoff, circuit breaker state machine,
correlation ids, log redaction, and the structured logger sinks.
"""

import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_resilience as res
from opsora_resilience import (
    CircuitBreaker,
    CircuitOpenError,
    StructuredLogger,
    is_transient_error,
    retry_with_backoff,
)

_RESILIENCE_ENV_VARS = [
    "OPSORA_TIMEOUT",
    "OPSORA_API_TIMEOUT",
    "OPSORA_RETRY_MAX_ATTEMPTS",
    "OPSORA_BREAKER_THRESHOLD",
    "OPSORA_BREAKER_COOLDOWN",
    "OPSORA_LOG_FILE",
    "OPSORA_LOG_LEVEL",
]


@pytest.fixture(autouse=True)
def _reset_resilience_state(monkeypatch):
    """Isolate module-level caches between tests."""
    for var in _RESILIENCE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    res.reset_config_cache()
    res.reset_breakers()
    res.reset_logger()
    yield
    res.reset_config_cache()
    res.reset_breakers()
    res.reset_logger()


# ---------------------------------------------------------------------------
# Configuration layering
# ---------------------------------------------------------------------------


class TestConfig:
    def test_builtin_defaults_when_file_missing(self, tmp_path):
        cfg = res.load_config(tmp_path / "does_not_exist.json")
        assert cfg.timeout_seconds == 40
        assert cfg.opsora_api_timeout_seconds == 120
        assert cfg.retry.max_attempts == 3
        assert cfg.retry.base_delay_seconds == 0.5
        assert cfg.circuit_breaker.failure_threshold == 5
        assert cfg.circuit_breaker.cooldown_seconds == 60.0

    def test_malformed_file_falls_back_to_defaults(self, tmp_path):
        bad = tmp_path / "resilience.json"
        bad.write_text("{not valid json!!", encoding="utf-8")
        cfg = res.load_config(bad)
        assert cfg.timeout_seconds == 40
        assert cfg.retry.max_attempts == 3

    def test_file_values_override_defaults(self, tmp_path):
        path = tmp_path / "resilience.json"
        path.write_text(json.dumps({
            "timeout_seconds": 99,
            "retry": {"max_attempts": 7},
            "circuit_breaker": {"failure_threshold": 2, "cooldown_seconds": 5.0},
        }), encoding="utf-8")
        cfg = res.load_config(path)
        assert cfg.timeout_seconds == 99
        assert cfg.retry.max_attempts == 7
        assert cfg.circuit_breaker.failure_threshold == 2
        assert cfg.circuit_breaker.cooldown_seconds == 5.0
        # Untouched keys keep defaults.
        assert cfg.opsora_api_timeout_seconds == 120

    def test_invalid_file_values_ignored(self, tmp_path):
        path = tmp_path / "resilience.json"
        path.write_text(json.dumps({
            "timeout_seconds": -5,
            "retry": {"max_attempts": 0},
        }), encoding="utf-8")
        cfg = res.load_config(path)
        assert cfg.timeout_seconds == 40
        assert cfg.retry.max_attempts == 3

    def test_env_overrides_win_over_file(self, tmp_path, monkeypatch):
        path = tmp_path / "resilience.json"
        path.write_text(json.dumps({"timeout_seconds": 99}), encoding="utf-8")
        monkeypatch.setenv("OPSORA_TIMEOUT", "12")
        cfg = res.load_config(path)
        assert cfg.timeout_seconds == 12

    def test_get_config_reflects_live_env_changes(self, monkeypatch):
        assert res.get_config().timeout_seconds == 40
        monkeypatch.setenv("OPSORA_TIMEOUT", "77")
        assert res.get_config().timeout_seconds == 77

    def test_reload_config_from_disk(self, tmp_path):
        path = tmp_path / "resilience.json"
        path.write_text(json.dumps({"timeout_seconds": 55}), encoding="utf-8")
        cfg = res.reload_config(path)
        assert cfg.timeout_seconds == 55
        assert res.get_config().timeout_seconds == 55


# ---------------------------------------------------------------------------
# Transient error classification
# ---------------------------------------------------------------------------


class _StatusError(Exception):
    """Mimics openai SDK APIStatusError shape."""

    def __init__(self, status_code: int):
        super().__init__(f"request failed with status {status_code}")
        self.status_code = status_code


class TestTransientClassification:
    @pytest.mark.parametrize("code", [500, 502, 503, 504, 429])
    def test_http_5xx_and_429_are_transient(self, code):
        assert is_transient_error(_StatusError(code)) is True

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_http_4xx_are_fatal(self, code):
        assert is_transient_error(_StatusError(code)) is False

    def test_url_error_is_transient(self):
        assert is_transient_error(URLError("connection refused")) is True

    def test_timeout_error_is_transient(self):
        assert is_transient_error(TimeoutError("read timed out")) is True

    def test_connection_error_is_transient(self):
        assert is_transient_error(ConnectionResetError("reset by peer")) is True

    def test_http_error_object_5xx(self):
        err = HTTPError("http://x", 503, "unavailable", {}, None)
        assert is_transient_error(err) is True

    def test_http_error_object_401(self):
        err = HTTPError("http://x", 401, "unauthorized", {}, None)
        assert is_transient_error(err) is False

    def test_sdk_class_name_matched_without_sdk(self):
        class APITimeoutError(Exception):
            pass

        assert is_transient_error(APITimeoutError("slow")) is True

    def test_wrapped_http_status_via_cause_chain(self):
        try:
            try:
                raise _StatusError(502)
            except _StatusError as inner:
                raise RuntimeError("provider call failed") from inner
        except RuntimeError as wrapped:
            assert is_transient_error(wrapped) is True

    def test_http_code_in_message_string(self):
        assert is_transient_error(RuntimeError("HTTP 503: service unavailable")) is True
        assert is_transient_error(RuntimeError("HTTP 404: not found")) is False

    def test_plain_value_error_is_fatal(self):
        assert is_transient_error(ValueError("bad input")) is False

    def test_none_is_not_transient(self):
        assert is_transient_error(None) is False


# ---------------------------------------------------------------------------
# Retry with backoff
# ---------------------------------------------------------------------------


class TestRetryWithBackoff:
    def test_success_first_try_no_retry(self):
        calls = []

        def fn():
            calls.append(1)
            return "ok"

        assert retry_with_backoff(fn, max_attempts=3, sleep=lambda s: None) == "ok"
        assert len(calls) == 1

    def test_retries_transient_then_succeeds(self):
        attempts = []

        def fn():
            attempts.append(1)
            if len(attempts) < 3:
                raise URLError("connection reset")
            return "recovered"

        result = retry_with_backoff(
            fn, max_attempts=5, base_delay=0.01, sleep=lambda s: None)
        assert result == "recovered"
        assert len(attempts) == 3

    def test_fatal_error_raises_immediately(self):
        attempts = []

        def fn():
            attempts.append(1)
            raise _StatusError(401)

        with pytest.raises(_StatusError):
            retry_with_backoff(fn, max_attempts=5, sleep=lambda s: None)
        assert len(attempts) == 1

    def test_exhausts_attempts_and_raises_last(self):
        def fn():
            raise URLError("still down")

        with pytest.raises(URLError, match="still down"):
            retry_with_backoff(fn, max_attempts=3, sleep=lambda s: None)

    def test_backoff_delays_increase_and_are_capped(self):
        delays = []

        def fn():
            raise URLError("down")

        with pytest.raises(URLError):
            retry_with_backoff(
                fn, max_attempts=5, base_delay=1.0, max_delay=2.5, jitter=0.0,
                sleep=delays.append)
        # 4 retries: 1.0, 2.0, 2.5 (capped), 2.5 (capped)
        assert delays == [1.0, 2.0, 2.5, 2.5]

    def test_on_retry_callback_invoked(self):
        events = []

        def fn():
            if not events:
                raise URLError("blip")
            return "done"

        retry_with_backoff(
            fn, max_attempts=3, sleep=lambda s: None,
            on_retry=lambda attempt, exc, delay: events.append((attempt, str(exc))))
        assert len(events) == 1
        assert events[0][0] == 1

    def test_zero_attempts_clamped_to_one(self):
        calls = []

        def fn():
            calls.append(1)
            return "ok"

        assert retry_with_backoff(fn, max_attempts=0, sleep=lambda s: None) == "ok"
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Circuit breaker state machine
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


class TestCircuitBreaker:
    def _breaker(self, clock=None, threshold=3, cooldown=60.0):
        return CircuitBreaker(
            "test-provider", failure_threshold=threshold,
            cooldown_seconds=cooldown, clock=clock or _FakeClock())

    def test_starts_closed_and_allows(self):
        b = self._breaker()
        assert b.state == "closed"
        assert b.allow_request() is True

    def test_opens_after_threshold_consecutive_failures(self):
        b = self._breaker(threshold=3)
        for _ in range(3):
            b.record_failure()
        assert b.state == "open"
        assert b.allow_request() is False

    def test_success_resets_failure_count(self):
        b = self._breaker(threshold=3)
        b.record_failure()
        b.record_failure()
        b.record_success()
        b.record_failure()
        b.record_failure()
        assert b.state == "closed"

    def test_half_open_after_cooldown(self):
        clock = _FakeClock()
        b = self._breaker(clock=clock, threshold=1, cooldown=60.0)
        b.record_failure()
        assert b.state == "open"
        clock.advance(61.0)
        assert b.state == "half-open"
        assert b.allow_request() is True  # probe admitted

    def test_half_open_admits_single_probe_only(self):
        clock = _FakeClock()
        b = self._breaker(clock=clock, threshold=1, cooldown=10.0)
        b.record_failure()
        clock.advance(11.0)
        assert b.allow_request() is True   # the probe
        assert b.allow_request() is False  # others fail fast while probe runs

    def test_probe_success_closes(self):
        clock = _FakeClock()
        b = self._breaker(clock=clock, threshold=1, cooldown=10.0)
        b.record_failure()
        clock.advance(11.0)
        b.allow_request()
        b.record_success()
        assert b.state == "closed"
        assert b.allow_request() is True

    def test_probe_failure_reopens(self):
        clock = _FakeClock()
        b = self._breaker(clock=clock, threshold=1, cooldown=10.0)
        b.record_failure()
        clock.advance(11.0)
        b.allow_request()
        b.record_failure()
        assert b.state == "open"
        assert b.allow_request() is False

    def test_status_snapshot_fields(self):
        b = self._breaker(threshold=2)
        b.record_failure()
        status = b.status()
        assert status["provider"] == "test-provider"
        assert status["state"] == "closed"
        assert status["consecutive_failures"] == 1
        assert status["failure_threshold"] == 2
        assert status["total_failures"] == 1

    def test_status_retry_after_counts_down(self):
        clock = _FakeClock()
        b = self._breaker(clock=clock, threshold=1, cooldown=60.0)
        b.record_failure()
        assert b.status()["retry_after_seconds"] == 60.0
        clock.advance(25.0)
        assert b.status()["retry_after_seconds"] == 35.0

    def test_reset_restores_closed(self):
        b = self._breaker(threshold=1)
        b.record_failure()
        assert b.state == "open"
        b.reset()
        assert b.state == "closed"
        assert b.allow_request() is True


class TestBreakerRegistry:
    def test_get_breaker_creates_per_provider(self):
        a = res.get_breaker("nvidia")
        b = res.get_breaker("alibaba")
        assert a is not b
        assert res.get_breaker("nvidia") is a

    def test_all_breaker_status_lists_seen_providers(self):
        res.get_breaker("nvidia")
        res.get_breaker("alibaba")
        status = res.all_breaker_status()
        assert set(status.keys()) == {"alibaba", "nvidia"}

    def test_reset_breakers_clears_registry(self):
        res.get_breaker("nvidia")
        res.reset_breakers()
        assert res.all_breaker_status() == {}

    def test_circuit_open_error_carries_provider(self):
        err = CircuitOpenError("nvidia", retry_after=42.0)
        assert "nvidia" in str(err)
        assert err.retry_after == 42.0


# ---------------------------------------------------------------------------
# Correlation ids
# ---------------------------------------------------------------------------


class TestCorrelationId:
    def test_new_turn_id_is_unique_hex(self):
        a = res.new_turn_correlation_id()
        b = res.new_turn_correlation_id()
        assert a != b
        assert len(a) == 32
        int(a, 16)  # valid hex

    def test_set_and_get_roundtrip(self):
        res.set_correlation_id("fixed-id-123")
        assert res.get_correlation_id() == "fixed-id-123"

    def test_get_or_new_creates_when_absent(self):
        res.set_correlation_id(None)
        cid = res.get_or_new_correlation_id()
        assert cid
        assert res.get_correlation_id() == cid


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_nvidia_key_masked(self):
        out = res.redact("key is nvapi-AbCdEfGh1234567890IjKlMnOp")
        assert "AbCdEfGh1234567890IjKlMnOp" not in out
        assert "nvapi-" in out

    def test_generic_secret_pair_masked(self):
        out = res._fallback_redact('api_key = "supersecretvalue1234567890"')
        assert "supersecretvalue1234567890" not in out

    def test_bearer_token_masked(self):
        out = res._fallback_redact("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6")
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6" not in out

    def test_innocent_text_unchanged(self):
        text = "provider call succeeded in 120ms"
        assert res.redact(text) == text

    def test_empty_string_passthrough(self):
        assert res.redact("") == ""


# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------


class TestStructuredLogger:
    def test_file_sink_writes_json_lines(self, tmp_path):
        log_file = tmp_path / "logs" / "test.log"
        logger = StructuredLogger(sink=str(log_file), level="INFO")
        res.set_correlation_id("corr-test-1")
        logger.info("provider_call_success", provider="nvidia", elapsed_ms=120)
        for handler in logger._logger.handlers:
            handler.flush()

        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "provider_call_success"
        assert record["level"] == "INFO"
        assert record["correlation_id"] == "corr-test-1"
        assert record["provider"] == "nvidia"
        assert record["elapsed_ms"] == 120
        assert "ts" in record

    def test_off_sink_writes_nothing(self, tmp_path):
        logger = StructuredLogger(sink="off")
        assert logger.sink == "off"
        logger.error("should_not_appear")  # must not raise

    def test_level_filtering(self, tmp_path):
        log_file = tmp_path / "level.log"
        logger = StructuredLogger(sink=str(log_file), level="WARNING")
        logger.info("too_low")
        logger.error("high_enough")
        for handler in logger._logger.handlers:
            handler.flush()

        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        events = [json.loads(line)["event"] for line in lines]
        assert events == ["high_enough"]

    def test_secrets_redacted_in_log_output(self, tmp_path):
        log_file = tmp_path / "redact.log"
        logger = StructuredLogger(sink=str(log_file), level="INFO")
        logger.info("call", api_key="nvapi-AbCdEfGh1234567890IjKlMnOp")
        for handler in logger._logger.handlers:
            handler.flush()

        content = log_file.read_text(encoding="utf-8")
        assert "AbCdEfGh1234567890IjKlMnOp" not in content

    def test_get_logger_singleton(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPSORA_LOG_FILE", "off")
        a = res.get_logger()
        b = res.get_logger()
        assert a is b

    def test_logger_never_raises_on_bad_details(self, tmp_path):
        logger = StructuredLogger(sink=str(tmp_path / "x.log"), level="INFO")

        class Unserializable:
            def __repr__(self):
                raise RuntimeError("no repr")

        # default=str in json.dumps keeps this alive; must not raise.
        logger.info("odd", payload=Unserializable())
