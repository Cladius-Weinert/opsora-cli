"""Comprehensive tests for opsora_cost.py cost tracking."""
import json
import logging
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add cmd directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_cost


class TestExtractUsage:
    """Tests for extract_usage function."""

    def test_extract_from_object_with_usage(self):
        """Test extracting usage from an object with usage attribute."""
        mock_response = MagicMock()
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50
        mock_usage.total_tokens = 150
        mock_response.usage = mock_usage

        result = opsora_cost.extract_usage(mock_response)
        assert result == {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

    def test_extract_from_dict_with_usage(self):
        """Test extracting usage from a dict response."""
        mock_response = {
            "usage": {
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300
            }
        }

        result = opsora_cost.extract_usage(mock_response)
        assert result == {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}

    def test_extract_missing_total_tokens_computed(self):
        """Test that total_tokens is computed when missing."""
        mock_response = MagicMock()
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50
        # total_tokens not set
        mock_usage.total_tokens = None
        mock_response.usage = mock_usage

        result = opsora_cost.extract_usage(mock_response)
        assert result["total_tokens"] == 150

    def test_extract_no_usage_returns_empty(self):
        """Test that empty dict is returned when no usage."""
        mock_response = MagicMock()
        mock_response.usage = None

        result = opsora_cost.extract_usage(mock_response)
        assert result == {}

    def test_extract_none_response_returns_empty(self):
        """Test that empty dict is returned for None."""
        result = opsora_cost.extract_usage(None)
        assert result == {}


class TestComputeCost:
    """Tests for _compute_cost internal function."""

    def test_known_model_cost(self):
        """Test cost computation for known model."""
        cost = opsora_cost._compute_cost("qwen-plus", 1_000_000, 1_000_000)
        # qwen-plus: (0.40, 1.20) per M tokens
        # 1M input * 0.40 + 1M output * 1.20 = 1.60
        assert cost == 1.60

    def test_known_model_cost_qwen_turbo(self):
        """Test cost for qwen-turbo (cheapest)."""
        cost = opsora_cost._compute_cost("qwen-turbo", 1_000_000, 1_000_000)
        # qwen-turbo: (0.05, 0.20) per M tokens
        assert cost == 0.25

    def test_known_model_cost_qwen_max(self):
        """Test cost for qwen-max (expensive)."""
        cost = opsora_cost._compute_cost("qwen-max", 1_000_000, 1_000_000)
        # qwen-max: (2.00, 6.00) per M tokens
        assert cost == 8.00

    def test_unknown_model_uses_default(self):
        """Test unknown model uses default pricing."""
        cost = opsora_cost._compute_cost("unknown-model", 1_000_000, 1_000_000)
        # default: (0.30, 0.60) per M tokens
        assert cost == 0.90

    def test_zero_tokens_zero_cost(self):
        """Test zero tokens gives zero cost."""
        cost = opsora_cost._compute_cost("qwen-plus", 0, 0)
        assert cost == 0.0

    def test_fractional_tokens(self):
        """Test cost with fractional token counts."""
        cost = opsora_cost._compute_cost("qwen-plus", 500_000, 250_000)
        # 0.5M * 0.40 + 0.25M * 1.20 = 0.20 + 0.30 = 0.50
        assert cost == 0.50


class TestCostTracker:
    """Tests for CostTracker class."""

    @pytest.fixture
    def tracker(self):
        return opsora_cost.CostTracker()

    def test_record_valid_usage(self, tracker):
        """Test recording valid usage."""
        entry = tracker.record("qwen-plus", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        assert entry is not None
        assert entry.model == "qwen-plus"
        assert entry.prompt_tokens == 100
        assert entry.completion_tokens == 50
        assert entry.total_tokens == 150
        assert entry.cost_usd > 0

    def test_record_empty_usage_returns_none(self, tracker):
        """Test recording empty usage returns None."""
        entry = tracker.record("qwen-plus", {})
        assert entry is None

    def test_record_missing_total_tokens(self, tracker):
        """Test recording with missing total_tokens."""
        entry = tracker.record("qwen-plus", {"prompt_tokens": 100, "completion_tokens": 50})
        assert entry is not None
        assert entry.total_tokens == 150

    def test_record_response_from_object(self, tracker):
        """Test record_response with object response."""
        mock_response = MagicMock()
        mock_response.model = "qwen-plus"
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50
        mock_usage.total_tokens = 150
        mock_response.usage = mock_usage

        entry = tracker.record_response(mock_response)
        assert entry is not None
        assert entry.model == "qwen-plus"

    def test_record_response_no_usage(self, tracker):
        """Test record_response with no usage."""
        mock_response = MagicMock()
        mock_response.model = "qwen-plus"
        mock_response.usage = None

        entry = tracker.record_response(mock_response)
        assert entry is None

    def test_session_total_empty(self, tracker):
        """Test session total when empty."""
        result = tracker.session_total()
        assert result["total_tokens"] == 0
        assert result["total_cost"] == 0.0
        assert result["total_calls"] == 0
        assert result["by_model"] == {}

    def test_session_total_multiple_entries(self, tracker):
        """Test session total with multiple entries."""
        tracker.record("qwen-plus", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        tracker.record("qwen-plus", {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300})
        tracker.record("qwen-turbo", {"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75})

        result = tracker.session_total()
        assert result["total_tokens"] == 525
        assert result["total_calls"] == 3
        assert "qwen-plus" in result["by_model"]
        assert "qwen-turbo" in result["by_model"]
        assert result["by_model"]["qwen-plus"]["tokens"] == 450
        assert result["by_model"]["qwen-plus"]["calls"] == 2
        assert result["by_model"]["qwen-turbo"]["tokens"] == 75
        assert result["by_model"]["qwen-turbo"]["calls"] == 1

    def test_render_summary_empty(self, tracker):
        """Test render_summary when empty."""
        summary = tracker.render_summary()
        assert "Belum ada usage" in summary

    def test_render_summary_with_data(self, tracker):
        """Test render_summary with recorded data."""
        tracker.record("qwen-plus", {"prompt_tokens": 1_000_000, "completion_tokens": 500_000, "total_tokens": 1_500_000})
        summary = tracker.render_summary()
        assert "qwen-plus" in summary
        assert "$" in summary
        assert "1,500,000" in summary or "1500000" in summary


class TestModelCostsDict:
    """Tests for MODEL_COSTS dictionary."""

    def test_all_costs_are_positive_tuples(self):
        for model, (input_cost, output_cost) in opsora_cost.MODEL_COSTS.items():
            assert input_cost >= 0, f"{model} input cost negative"
            assert output_cost >= 0, f"{model} output cost negative"

    def test_contains_expected_models(self):
        expected = ["qwen-plus", "qwen-turbo", "qwen-max", "qwen3-coder-flash", "meta/llama-3.1-70b-instruct"]
        for model in expected:
            assert model in opsora_cost.MODEL_COSTS

    def test_default_cost_reasonable(self):
        input_cost, output_cost = opsora_cost._DEFAULT_COST
        assert 0 < input_cost < 5
        assert 0 < output_cost < 5


class TestConfigLoading:
    """Tests for loading pricing from config/model_costs.json."""

    def test_shipped_config_exists_and_is_live(self):
        """The repo config file parses and its values are reflected in MODEL_COSTS."""
        assert opsora_cost.CONFIG_PATH.is_file(), f"missing {opsora_cost.CONFIG_PATH}"
        with open(opsora_cost.CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert data["models"], "config must define at least one model"
        for model, rates in data["models"].items():
            assert model in opsora_cost.MODEL_COSTS
            assert opsora_cost.MODEL_COSTS[model] == tuple(rates)

    def test_known_model_returns_expected_price(self):
        """qwen-plus pricing must match the documented $/M-token rates."""
        assert opsora_cost.MODEL_COSTS["qwen-plus"] == (0.40, 1.20)
        # 1M input tokens at $0.40/M, 0 output
        assert opsora_cost._compute_cost("qwen-plus", 1_000_000, 0) == pytest.approx(0.40)

    def test_load_from_custom_file(self, tmp_path):
        """Values from a config file override pricing."""
        cfg = tmp_path / "model_costs.json"
        cfg.write_text(json.dumps({
            "default_cost": [1.0, 2.0],
            "models": {"custom-model": [0.5, 1.5]},
        }), encoding="utf-8")
        costs, default = opsora_cost._load_model_costs(cfg)
        assert costs["custom-model"] == (0.5, 1.5)
        assert default == (1.0, 2.0)

    def test_fallback_when_file_missing(self, tmp_path, monkeypatch, caplog):
        """Missing config file -> built-in defaults plus a logged warning."""
        monkeypatch.setattr(opsora_cost, "CONFIG_PATH", tmp_path / "does_not_exist.json")
        with caplog.at_level(logging.WARNING):
            costs, default = opsora_cost._load_model_costs()
        assert costs == opsora_cost._BUILTIN_MODEL_COSTS
        assert default == opsora_cost._BUILTIN_DEFAULT_COST
        assert "built-in defaults" in caplog.text

    def test_fallback_when_file_malformed(self, tmp_path, monkeypatch, caplog):
        """Unparseable JSON -> built-in defaults plus a logged warning."""
        cfg = tmp_path / "model_costs.json"
        cfg.write_text("{this is not valid json", encoding="utf-8")
        monkeypatch.setattr(opsora_cost, "CONFIG_PATH", cfg)
        with caplog.at_level(logging.WARNING):
            costs, default = opsora_cost._load_model_costs()
        assert costs == opsora_cost._BUILTIN_MODEL_COSTS
        assert default == opsora_cost._BUILTIN_DEFAULT_COST
        assert "built-in defaults" in caplog.text

    def test_fallback_when_structure_wrong(self, tmp_path):
        """Valid JSON without a 'models' object -> built-in defaults."""
        cfg = tmp_path / "model_costs.json"
        cfg.write_text(json.dumps({"prices": {"qwen-plus": [1, 2]}}), encoding="utf-8")
        costs, default = opsora_cost._load_model_costs(cfg)
        assert costs == opsora_cost._BUILTIN_MODEL_COSTS
        assert default == opsora_cost._BUILTIN_DEFAULT_COST

    def test_malformed_entries_skipped_not_fatal(self, tmp_path):
        """Bad individual entries are skipped; valid ones still load."""
        cfg = tmp_path / "model_costs.json"
        cfg.write_text(json.dumps({
            "models": {
                "good": [1.0, 2.0],
                "one_value": [1.0],
                "negative": [-1.0, 2.0],
                "not_numbers": ["a", "b"],
            },
        }), encoding="utf-8")
        costs, _ = opsora_cost._load_model_costs(cfg)
        assert costs["good"] == (1.0, 2.0)
        assert "one_value" not in costs
        assert "negative" not in costs
        assert "not_numbers" not in costs


class TestEntryDataclass:
    """Tests for _Entry dataclass."""

    def test_entry_creation(self):
        entry = opsora_cost._Entry(
            model="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            timestamp=1234567890.0
        )
        assert entry.model == "test-model"
        assert entry.prompt_tokens == 100
        assert entry.completion_tokens == 50
        assert entry.total_tokens == 150
        assert entry.cost_usd == 0.001
        assert entry.timestamp == 1234567890.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])