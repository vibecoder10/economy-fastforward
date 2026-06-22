"""Lock: onboarding's "required keys" is derived from the pipeline's gate.

Before this, three places disagreed on which API keys a tenant needs:
  - onboarding /status (dashboard.py) demanded 4 keys (anthropic, elevenlabs,
    elevenlabs_voice_id, kie)
  - the pipeline /readiness gate (pipeline.py PIPELINE_REQUIRED_KEYS) needs only kie
A Kie-only tenant — correctly set up to actually generate — was therefore marked
"onboarding incomplete" forever and nagged to add keys the pipeline routes
through Kie anyway. This pins the single source of truth so they can't drift.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _backend() -> Path:
    return Path(__file__).resolve().parents[2]


def test_dashboard_derives_required_keys_from_pipeline():
    src = (_backend() / "routes" / "dashboard.py").read_text()
    assert "from routes.pipeline import PIPELINE_REQUIRED_KEYS" in src, (
        "dashboard onboarding-status must import PIPELINE_REQUIRED_KEYS as the "
        "single source of truth"
    )
    assert re.search(r"required_keys\s*=\s*\[k\[.key.\]\s+for\s+k\s+in\s+PIPELINE_REQUIRED_KEYS\]", src), (
        "required_keys must be DERIVED from PIPELINE_REQUIRED_KEYS, not hardcoded"
    )
    # The old hardcoded 4-key list must be gone.
    assert not re.search(r"required_keys\s*=\s*\[\s*[\"']anthropic_api_key", src), (
        "dashboard still hardcodes the 4-key required list — it will drift again"
    )
    print("✅ test_dashboard_derives_required_keys_from_pipeline")


def test_pipeline_required_keys_is_just_kie():
    """If the canonical required set ever changes, this documents the intent:
    Kie is the only hard requirement (it powers text+image+video+voice)."""
    src = (_backend() / "routes" / "pipeline.py").read_text()
    m = re.search(r"PIPELINE_REQUIRED_KEYS\s*=\s*\[(.*?)\]", src, re.DOTALL)
    assert m, "PIPELINE_REQUIRED_KEYS not found"
    block = m.group(1)
    assert "kie_ai_api_key" in block, "kie_ai_api_key must be required"
    # No other *required* key (anthropic/elevenlabs route through Kie → optional).
    for k in ("anthropic_api_key", "elevenlabs_api_key", "elevenlabs_voice_id"):
        assert k not in block, f"{k} should be OPTIONAL, not in PIPELINE_REQUIRED_KEYS"
    print("✅ test_pipeline_required_keys_is_just_kie")


TESTS = [
    test_dashboard_derives_required_keys_from_pipeline,
    test_pipeline_required_keys_is_just_kie,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
