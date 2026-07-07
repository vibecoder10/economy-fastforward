"""Functional test: prove the tenant narrator voice config reaches ElevenLabs.

Context (DvsU, 2026-07-07): the `elevenlabs_voice_id` vault secret was exposed
in onboarding but never loaded into the runtime env, so every tenant's narrator
ran on the process default voice. Fixed by loading three voice-config secrets
in `pipeline_executor._ensure_initialized` (voice id, model id, style) and
honoring ELEVENLABS_MODEL_ID / ELEVENLABS_VOICE_STYLE in the ElevenLabs client.

This test guards the whole seam:

1. **Static check** — pipeline_executor.py loads all three voice-config
   secrets AND snapshots/restores process-level defaults so tenants without
   a vault override keep the .env voice (the pre-fix behavior).
2. **Runtime check** — with the env vars set, ElevenLabsClient targets the
   custom voice URL and sends the pinned model_id and style in the payload.
3. **Default check** — with no env vars, the payload stays byte-identical to
   the pre-fix behavior (turbo model, no style key).

To run:
    cd storyengine/backend && venv/bin/python3 tests/functional/test_narrator_voice_wiring.py
"""
import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(REPO / "skills" / "video-pipeline"))

FAILURES = []


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def test_static_wiring():
    print("\n== 1. static: pipeline_executor loads + restores voice config ==")
    src = (BACKEND / "pipeline_executor.py").read_text()
    for key in ("elevenlabs_voice_id", "elevenlabs_model_id", "elevenlabs_voice_style"):
        check(f"keys_to_load includes {key}", f'"{key}"' in src)
    check("process defaults snapshot exists", "process_voice_defaults" in src)
    vault_src = (BACKEND / "vault.py").read_text()
    for key in ("ELEVENLABS_MODEL_ID", "ELEVENLABS_VOICE_STYLE"):
        check(f"vault SECRET_ENV_MAP includes {key}", key in vault_src)


class _CapturePost:
    """Stub httpx.AsyncClient that records the TTS request instead of sending it."""

    captured = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None, timeout=None):
        _CapturePost.captured = {"url": url, "json": json}

        class _Resp:
            content = b"AUDIO"
            headers = {"content-type": "audio/mpeg"}

            def raise_for_status(self):
                pass

        return _Resp()


def test_runtime_custom_voice():
    print("\n== 2. runtime: custom voice/model/style reach the request ==")
    import httpx
    from shared.clients.elevenlabs_client import ElevenLabsClient

    os.environ["ELEVENLABS_API_KEY"] = "fake-key-for-test"
    os.environ["ELEVENLABS_VOICE_ID"] = "Wq15xSaY3gWvazBRaGEU"
    os.environ["ELEVENLABS_MODEL_ID"] = "eleven_multilingual_v2"
    os.environ["ELEVENLABS_VOICE_STYLE"] = "0.25"
    os.environ.pop("KIE_AI_API_KEY", None)

    real = httpx.AsyncClient
    httpx.AsyncClient = _CapturePost
    try:
        client = ElevenLabsClient()
        result = asyncio.run(client.generate_voice("The manufacturer had been right."))
        cap = _CapturePost.captured
        check("custom voice in URL", "Wq15xSaY3gWvazBRaGEU" in cap["url"], cap["url"])
        check("model pinned to multilingual v2", cap["json"]["model_id"] == "eleven_multilingual_v2",
              cap["json"]["model_id"])
        check("style sent", cap["json"]["voice_settings"].get("style") == 0.25,
              str(cap["json"]["voice_settings"]))
        check("stability per long-form profile", cap["json"]["voice_settings"]["stability"] == 0.5)
        check("speaker boost on", cap["json"]["voice_settings"]["use_speaker_boost"] is True)
        check("audio returned", result.get("audio_content") == b"AUDIO")

        print("\n== 3. defaults: pre-fix behavior preserved without env ==")
        os.environ.pop("ELEVENLABS_MODEL_ID", None)
        os.environ.pop("ELEVENLABS_VOICE_STYLE", None)
        os.environ.pop("ELEVENLABS_VOICE_ID", None)
        client2 = ElevenLabsClient()
        asyncio.run(client2.generate_voice("Default path."))
        cap2 = _CapturePost.captured
        check("default model stays turbo", cap2["json"]["model_id"] == "eleven_turbo_v2_5",
              cap2["json"]["model_id"])
        check("no style key by default", "style" not in cap2["json"]["voice_settings"],
              str(cap2["json"]["voice_settings"]))
        # explicit dialogue style still wins over env
        os.environ["ELEVENLABS_VOICE_STYLE"] = "0.25"
        asyncio.run(client2.generate_voice("Dialogue line.", style=0.9))
        cap3 = _CapturePost.captured
        check("explicit style beats env", cap3["json"]["voice_settings"].get("style") == 0.9,
              str(cap3["json"]["voice_settings"]))
    finally:
        httpx.AsyncClient = real
        for var in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID",
                    "ELEVENLABS_MODEL_ID", "ELEVENLABS_VOICE_STYLE"):
            os.environ.pop(var, None)


if __name__ == "__main__":
    test_static_wiring()
    test_runtime_custom_voice()
    if FAILURES:
        print(f"\nRESULT: FAIL ({len(FAILURES)}): {FAILURES}")
        sys.exit(1)
    print("\nRESULT: ALL PASS — narrator voice config is wired vault -> env -> ElevenLabs request")
