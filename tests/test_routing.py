"""Comprehensive tests for opsora_routing.py intent router and model selection."""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add cmd directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_routing


class TestIntentRouterClassification:
    """Tests for IntentRouter.classify() method."""

    @pytest.fixture
    def router(self):
        return opsora_routing.IntentRouter()

    # --- Code intent tests ---
    def test_code_write_function(self, router):
        result = router.classify("write a function to parse JSON")
        assert result == "code"

    def test_code_create_class(self, router):
        result = router.classify("create a Python class for user management")
        assert result == "code"

    def test_code_debug_bug(self, router):
        result = router.classify("debug this bug in my script")
        assert result == "code"

    def test_code_fix_error(self, router):
        result = router.classify("fix the error in main.py")
        assert result == "code"

    def test_code_refactor(self, router):
        result = router.classify("refactor this class definition")
        assert result == "code"

    def test_code_python_keyword(self, router):
        result = router.classify("python script to process data")
        assert result == "code"

    def test_code_bash_script(self, router):
        result = router.classify("bash script to backup files")
        assert result == "code"

    def test_code_api_endpoint(self, router):
        result = router.classify("create API endpoint for users")
        assert result == "code"

    def test_code_indonesian_bikin(self, router):
        result = router.classify("bikin fungsi untuk login")
        assert result == "code"

    def test_code_indonesian_buat(self, router):
        result = router.classify("buat script python sederhana")
        assert result == "code"

    def test_code_indonesian_perbaiki(self, router):
        result = router.classify("perbaiki bug di kode ini")
        assert result == "code"

    def test_code_git_commit(self, router):
        result = router.classify("git commit and push changes")
        assert result == "code"

    def test_code_docker(self, router):
        result = router.classify("write Dockerfile for deployment")
        assert result == "code"

    def test_code_test_pytest(self, router):
        result = router.classify("write pytest unit tests")
        assert result == "code"

    # --- Quick intent tests ---
    def test_quick_yes_no(self, router):
        result = router.classify("yes")
        assert result == "quick"

    def test_quick_what_is(self, router):
        result = router.classify("what is Python?")
        assert result == "quick"

    def test_quick_apa_itu(self, router):
        result = router.classify("apa itu API?")
        assert result == "quick"

    def test_quick_how_to(self, router):
        result = router.classify("how to install package?")
        assert result == "quick"

    def test_quick_gimana(self, router):
        result = router.classify("gimana cara setup venv?")
        assert result == "quick"

    def test_quick_convert(self, router):
        result = router.classify("convert JSON to YAML")
        assert result == "quick"

    def test_quick_tldr(self, router):
        result = router.classify("tldr this article")
        assert result == "quick"

    def test_quick_ringkasan(self, router):
        result = router.classify("ringkasan dokumen ini")
        assert result == "quick"

    def test_quick_translate(self, router):
        result = router.classify("translate this to Indonesian")
        assert result == "quick"

    def test_quick_terjemah(self, router):
        result = router.classify("terjemah teks ini")
        assert result == "quick"

    def test_quick_short_prompt(self, router):
        result = router.classify("ok")
        assert result == "quick"

    def test_quick_indonesian_ya(self, router):
        result = router.classify("ya lanjutkan")
        assert result == "quick"

    # --- Analysis intent tests ---
    def test_analysis_analyze(self, router):
        result = router.classify("analyze this code architecture")
        assert result == "analysis"

    def test_analysis_compare(self, router):
        result = router.classify("compare these two approaches")
        assert result == "analysis"

    def test_analysis_review(self, router):
        result = router.classify("review my pull request")
        assert result == "analysis"

    def test_analysis_explain(self, router):
        result = router.classify("explain how this function works")
        assert result == "analysis"

    def test_analysis_research(self, router):
        result = router.classify("research best practices for caching")
        assert result == "analysis"

    def test_analysis_architecture(self, router):
        result = router.classify("architecture design for microservices")
        assert result == "analysis"

    def test_analysis_security(self, router):
        result = router.classify("security audit of this code")
        assert result == "analysis"

    def test_analysis_performance(self, router):
        result = router.classify("performance optimization tips")
        assert result == "analysis"

    def test_analysis_indonesian_analisis(self, router):
        result = router.classify("analisis performa aplikasi ini")
        assert result == "analysis"

    def test_analysis_indonesian_jelaskan(self, router):
        result = router.classify("jelaskan arsitektur sistem ini")
        assert result == "analysis"

    # --- Cloud intent tests ---
    def test_cloud_aws(self, router):
        result = router.classify("deploy to AWS EC2")
        assert result == "cloud"

    def test_cloud_azure(self, router):
        result = router.classify("azure deployment guide")
        assert result == "cloud"

    def test_cloud_gcp(self, router):
        result = router.classify("GCP cloud run setup")
        assert result == "cloud"

    def test_cloud_kubernetes(self, router):
        result = router.classify("kubernetes deployment yaml")
        assert result == "cloud"

    def test_cloud_fly_io(self, router):
        result = router.classify("deploy to fly.io")
        assert result == "cloud"

    def test_cloud_vercel(self, router):
        result = router.classify("vercel deployment config")
        assert result == "cloud"

    def test_cloud_docker(self, router):
        result = router.classify("docker container orchestration")
        assert result == "cloud"

    def test_cloud_vps(self, router):
        result = router.classify("VPS server setup")
        assert result == "cloud"

    def test_cloud_cdn(self, router):
        result = router.classify("CDN and load balancer config")
        assert result == "cloud"

    # --- Creative intent tests ---
    def test_creative_write_story(self, router):
        result = router.classify("write a short story about AI")
        assert result == "creative"

    def test_creative_poem(self, router):
        result = router.classify("create a poem about coding")
        assert result == "creative"

    def test_creative_blog(self, router):
        result = router.classify("write blog post about React")
        assert result == "creative"

    def test_creative_marketing(self, router):
        result = router.classify("marketing copy for product launch")
        assert result == "creative"

    def test_creative_brand(self, router):
        result = router.classify("brand name suggestions for startup")
        assert result == "creative"

    def test_creative_indonesian_cerita(self, router):
        result = router.classify("buat cerita pendek tentang robot")
        assert result == "creative"

    def test_creative_indonesian_artikel(self, router):
        result = router.classify("tulis artikel tentang Python")
        assert result == "creative"

    # --- Vision intent tests ---
    def test_vision_image(self, router):
        result = router.classify("analyze this image")
        assert result == "vision"

    def test_vision_screenshot(self, router):
        result = router.classify("what's in this screenshot?")
        assert result == "vision"

    def test_vision_diagram(self, router):
        result = router.classify("explain this diagram")
        assert result == "vision"

    def test_vision_ocr(self, router):
        result = router.classify("extract text from image")
        assert result == "vision"

    def test_vision_ui(self, router):
        result = router.classify("review this UI design")
        assert result == "vision"

    # --- General/fallback tests ---
    def test_general_fallback(self, router):
        result = router.classify("hello world")
        assert result == "general"

    def test_general_greeting(self, router):
        result = router.classify("hi there how are you")
        assert result == "general"

    def test_general_random(self, router):
        result = router.classify("random text without keywords")
        assert result == "general"

    def test_empty_prompt(self, router):
        result = router.classify("")
        assert result == "general"

    def test_whitespace_only(self, router):
        result = router.classify("   ")
        assert result == "general"


class TestRouteFunction:
    """Tests for the route() function."""

    def test_route_code_prefers_coder_model(self):
        provider, model = opsora_routing.route(
            "write a python function",
            available_providers={"alibaba": ["qwen3-coder-flash", "qwen-plus"]}
        )
        assert provider == "alibaba"
        assert "coder" in model.lower()

    def test_route_quick_prefers_turbo(self):
        provider, model = opsora_routing.route(
            "what is python?",
            available_providers={"alibaba": ["qwen-turbo", "qwen-plus"]}
        )
        assert provider == "alibaba"
        assert model == "qwen-turbo"

    def test_route_analysis_prefers_max(self):
        provider, model = opsora_routing.route(
            "analyze this architecture",
            available_providers={"alibaba": ["qwen-max", "qwen-plus"]}
        )
        assert provider == "alibaba"
        assert model == "qwen-max"

    def test_route_vision_prefers_vision_model(self):
        provider, model = opsora_routing.route(
            "analyze this image",
            available_providers={"nvidia": ["meta/llama-3.2-11b-vision-instruct", "meta/llama-3.1-70b-instruct"]}
        )
        assert provider == "nvidia"
        assert "vision" in model.lower()

    def test_route_cloud_prefers_reasoning(self):
        provider, model = opsora_routing.route(
            "deploy to kubernetes",
            available_providers={"nvidia": ["nvidia/nemotron-3-ultra-550b-a55b", "meta/llama-3.1-70b-instruct"]}
        )
        assert provider == "nvidia"
        assert "ultra" in model.lower() or "super" in model.lower()

    def test_route_prefer_cost(self):
        provider, model = opsora_routing.route(
            "simple task",
            available_providers={"alibaba": ["qwen-turbo", "qwen-max"]},
            prefer_cost=True
        )
        assert model == "qwen-turbo"

    def test_route_prefer_speed(self):
        provider, model = opsora_routing.route(
            "quick question",
            available_providers={"alibaba": ["qwen3-coder-flash", "qwen-max"]},
            prefer_speed=True
        )
        assert "flash" in model.lower() or "turbo" in model.lower()

    def test_route_required_capability(self):
        provider, model = opsora_routing.route(
            "analyze image",
            available_providers={"nvidia": ["meta/llama-3.2-11b-vision-instruct", "meta/llama-3.1-70b-instruct"]},
            required_capability="vision"
        )
        assert "vision" in model.lower()

    def test_route_no_providers_fallback(self):
        provider, model = opsora_routing.route(
            "any prompt",
            available_providers={}
        )
        assert provider == "alibaba"
        assert model == "qwen3-coder-flash"

    def test_route_multiple_providers_picks_best(self):
        provider, model = opsora_routing.route(
            "write code",
            available_providers={
                "alibaba": ["qwen-plus"],
                "nvidia": ["meta/llama-3.1-70b-instruct"]
            }
        )
        # Should prefer coder model if available
        assert provider in ("alibaba", "nvidia")


class TestModelCosts:
    """Tests for model cost dictionary."""

    def test_costs_exist_for_main_models(self):
        costs = opsora_routing._DEFAULT_COSTS
        assert "qwen-plus" in costs
        assert "qwen-turbo" in costs
        assert "qwen-max" in costs
        assert "qwen3-coder-flash" in costs
        assert "meta/llama-3.1-70b-instruct" in costs

    def test_costs_format(self):
        for model, (input_cost, output_cost) in opsora_routing._DEFAULT_COSTS.items():
            assert input_cost >= 0
            assert output_cost >= 0


class TestPatternMatching:
    """Tests for internal pattern matching logic."""

    def test_code_patterns_compile(self):
        for category, patterns in opsora_routing._PATTERNS.items():
            for pattern in patterns:
                assert pattern.pattern  # Should be valid regex

    def test_weights_exist_for_all_categories(self):
        for category in opsora_routing._PATTERNS:
            assert category in opsora_routing._WEIGHTS


class TestGetAvailableModels:
    """Tests for _get_available_models helper."""

    def test_filters_unavailable_providers(self):
        with patch('opsora_routing.is_provider_available') as mock_avail:
            mock_avail.side_effect = lambda p: p in ["alibaba", "nvidia"]
            with patch('opsora_routing.get_provider_order', return_value=["alibaba", "nvidia", "openai"]):
                with patch('opsora_routing.PROVIDER_MODELS', {"alibaba": "qwen-plus", "nvidia": "llama-70b", "openai": "gpt-4o"}):
                    available = opsora_routing._get_available_models()
                    assert "alibaba" in available
                    assert "nvidia" in available
                    assert "openai" not in available


class TestSelectBestModel:
    """Tests for _select_best_model internal function."""

    def test_returns_first_when_no_candidates_score(self):
        available = {"alibaba": ["qwen-plus"]}
        provider, model = opsora_routing._select_best_model("general", available)
        assert provider == "alibaba"
        assert model == "qwen-plus"

    def test_raises_when_no_model_has_required_capability(self):
        # Fail loudly, not silently: a vision requirement with no vision
        # model must raise, never fall back to a text-only model.
        available = {"nvidia": ["meta/llama-3.1-70b-instruct"]}
        with pytest.raises(opsora_routing.NoCapableModelError):
            opsora_routing._select_best_model(
                "vision", available, required_capability="vision"
            )


class TestCapabilityAwareness:
    """Capability map, aliases, and hard-filter behavior (Phase 1 task 11)."""

    def test_model_has_capability_vision(self):
        assert opsora_routing.model_has_capability("meta/llama-3.2-11b-vision-instruct", "vision")
        assert opsora_routing.model_has_capability("nvidia/neva-22b", "vision")
        assert not opsora_routing.model_has_capability("meta/llama-3.1-70b-instruct", "vision")

    def test_model_has_capability_coding_aliases(self):
        # "code", "coding" are aliases of the same capability
        assert opsora_routing.model_has_capability("qwen3-coder-flash", "coding")
        assert opsora_routing.model_has_capability("qwen3-coder-flash", "code")
        assert opsora_routing.model_has_capability("deepseek-ai/deepseek-coder-6.7b", "coding")
        assert not opsora_routing.model_has_capability("qwen-plus", "coding")

    def test_model_has_capability_unknown_literal_fallback(self):
        # Unknown capability strings keep legacy literal-substring semantics
        assert opsora_routing.model_has_capability("qwen-max", "max")
        assert not opsora_routing.model_has_capability("qwen-plus", "max")

    def test_capability_filter_uses_keywords_not_literal_name(self):
        # Regression: the old filter matched the literal capability string
        # against the model name, so required_capability="coding" wrongly
        # rejected "qwen3-coder-flash" (contains "coder", not "coding").
        provider, model = opsora_routing._select_best_model(
            "code", {"alibaba": ["qwen3-coder-flash"]}, required_capability="coding"
        )
        assert (provider, model) == ("alibaba", "qwen3-coder-flash")

    def test_vision_intent_derives_hard_capability_requirement(self):
        # A vision prompt with no vision model available must fail loudly
        with pytest.raises(opsora_routing.NoCapableModelError):
            opsora_routing.route(
                "analyze this image",
                available_providers={"nvidia": ["meta/llama-3.1-70b-instruct"]},
            )

    def test_vision_intent_still_routes_to_vision_model(self):
        provider, model = opsora_routing.route(
            "analyze this image",
            available_providers={"nvidia": ["meta/llama-3.2-11b-vision-instruct",
                                            "meta/llama-3.1-70b-instruct"]},
        )
        assert provider == "nvidia"
        assert "vision" in model.lower()

    def test_no_capability_constraint_keeps_legacy_behavior(self):
        # Non-vision intents impose no hard filter — general models remain
        # eligible and nothing raises.
        provider, model = opsora_routing.route(
            "hello there, how are you today?",
            available_providers={"nvidia": ["meta/llama-3.1-70b-instruct"]},
        )
        assert (provider, model) == ("nvidia", "meta/llama-3.1-70b-instruct")

    def test_route_no_providers_with_capability_raises(self):
        with pytest.raises(opsora_routing.NoCapableModelError):
            opsora_routing.route(
                "analyze this image",
                available_providers={},
                required_capability="vision",
            )

    def test_resolve_required_capability_explicit_wins(self):
        assert opsora_routing.resolve_required_capability("fast", "vision") == "fast"
        assert opsora_routing.resolve_required_capability(None, "vision") == "vision"
        assert opsora_routing.resolve_required_capability(None, "code") is None
        assert opsora_routing.resolve_required_capability(None, "general") is None


class TestFallbackCandidates:
    """Capability-aware fallback candidate selection (Phase 1 task 11)."""

    def test_vision_fallback_filters_incapable_models(self):
        cands = opsora_routing.fallback_candidates(
            "analyze this screenshot",
            available_providers={
                "nvidia": ["meta/llama-3.2-11b-vision-instruct", "meta/llama-3.1-70b-instruct"],
                "alibaba": ["qwen-plus"],
            },
        )
        # Only the vision-capable model survives the filter
        assert cands == [("nvidia", "meta/llama-3.2-11b-vision-instruct")]

    def test_excludes_failed_pairs(self):
        cands = opsora_routing.fallback_candidates(
            "write a function to parse CSV",
            available_providers={
                "alibaba": ["qwen3-coder-flash", "qwen3-coder-plus"],
            },
            exclude=[("alibaba", "qwen3-coder-flash")],
        )
        assert ("alibaba", "qwen3-coder-flash") not in cands
        assert ("alibaba", "qwen3-coder-plus") in cands

    def test_raises_when_no_capable_fallback_after_exclusions(self):
        # The only vision model already failed → must fail loudly
        with pytest.raises(opsora_routing.NoCapableModelError):
            opsora_routing.fallback_candidates(
                "analyze this screenshot",
                available_providers={
                    "nvidia": ["meta/llama-3.2-11b-vision-instruct", "meta/llama-3.1-70b-instruct"],
                },
                exclude=[("nvidia", "meta/llama-3.2-11b-vision-instruct")],
            )

    def test_no_capability_constraint_returns_all_non_excluded(self):
        cands = opsora_routing.fallback_candidates(
            "hello there, how are you today?",
            available_providers={
                "alibaba": ["qwen-plus"],
                "nvidia": ["meta/llama-3.1-70b-instruct"],
            },
        )
        assert set(cands) == {("alibaba", "qwen-plus"), ("nvidia", "meta/llama-3.1-70b-instruct")}

    def test_explicit_capability_overrides_intent(self):
        # Prompt classifies as code, but caller demands fast capability
        cands = opsora_routing.fallback_candidates(
            "write a function to parse CSV",
            available_providers={
                "alibaba": ["qwen3-coder-flash", "qwen-turbo", "qwen-plus"],
            },
            required_capability="fast",
        )
        models = [m for _, m in cands]
        assert "qwen-turbo" in models
        assert "qwen-plus" not in models


if __name__ == "__main__":
    pytest.main([__file__, "-v"])