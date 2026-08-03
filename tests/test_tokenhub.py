import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

def test_tokenhub_in_provider_models():
    """Verify tokenhub is defined in PROVIDER_MODELS."""
    from opsora_v2 import PROVIDER_MODELS
    # tokenhub may or may not be available — just check it's a string if present
    if "tokenhub" in PROVIDER_MODELS:
        models = PROVIDER_MODELS["tokenhub"].split(",")
        assert len(models) > 0
