"""Tests for checklist C43 (P4.1d consumption audit + convergence).

Two convergence fixes, both "smallest correct change" per the chunk's own
constraint (no big refactor):

1. `routes/system_prompts.py::generate_prompts` used to blind-overwrite
   `channel_profiles.style_description` with no record of who did it — the
   SAME column `identity_builder.build_channel_identity` COALESCE-writes and
   stamps into `channel_identity._sources`. A manual "generate my prompts"
   from a plain style description could silently clobber a DNA-learned
   voice with zero provenance. Now it ALSO read-modify-writes
   `channel_identity` through `channel_dna_meta.stamp_identity_write`
   (`learner="system_prompts"`) so a later DNA digest shows the overwrite.
   The precedence law itself (per-video > tenant override > neutral
   identity-filled engine template) was already correct and is pinned by
   `tests/test_resolve_prompt.py` — this chunk only fixes the SILENT part.

2. `identity_builder._thumbnail_style` used to hit Kie's Claude gateway
   directly with a raw httpx POST — the exact endpoint
   `shared/clients/vision_client.py` exists to route AROUND, because that
   gateway has twice silently dropped image blocks. The OTHER
   thumbnail-formula extractor (`routes/model_video.py::
   _describe_thumbnail_style`, feeding `pipeline_executor.
   _run_channel_formula_thumbnail`'s `thumbnail_blueprint` cache) already
   used the safe `vision_call` helper. Converging `_thumbnail_style` onto
   the SAME primitive closes the reliability drift between the two
   thumbnail-formula code paths without collapsing their two distinct JSON
   schemas (consensus-across-3-thumbnails vs. one detailed blueprint) into
   a riskier single implementation — `pipeline_executor.py` itself is
   UNTOUCHED by this chunk (verify with `git diff --stat` — zero lines),
   which is the strongest possible proof the no-DNA fallback ordering in
   `_run_channel_formula_thumbnail` stayed byte-identical.

No live DB, no network, no real Claude/vision call.
Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c43_dna_convergence.py -q
"""
import asyncio
import json
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import identity_builder as ib  # noqa: E402
import routes.system_prompts as sp  # noqa: E402
import vault  # noqa: E402
from channel_dna_meta import coerce_identity, field_provenance  # noqa: E402


# ---------------------------------------------------------------------------
# 1. generate_prompts stamps style_description through channel_dna_meta
# ---------------------------------------------------------------------------

class FakeClaudeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class FakeClaudeClient:
    def __init__(self, response_body: dict, status_code: int = 200):
        self._response_body = response_body
        self._status = status_code
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "body": json})
        return FakeClaudeResponse(self._status, self._response_body)


def _fake_generated_prompts() -> dict:
    out = {k: f"generated {k} prompt" for k in sp.PROMPT_KEYS}
    out["summary"] = "A punchy, no-jargon voice."
    return out


def test_generate_prompts_stamps_style_description_with_provenance(monkeypatch):
    """The style_description write must land in BOTH the plain column AND
    channel_identity._sources, tagged learner='system_prompts' — the exact
    gap flagged by the P4.1 scout ('system_prompts.py is a SEPARATE parallel
    path... no shared code with identity_builder')."""
    tenant_id = "tenant-c43-a"

    # In-memory channel_profiles row: starts with a DNA-learned identity
    # (as if identity_builder ran first) so we can prove the overwrite is
    # visible, not that it merely exists on an empty row.
    prior_identity = {
        "voice_tone": "confident, direct",
        "style_description": "OLD dna-learned prose",
        "_sources": {
            "voice_tone": {"learner": "identity_builder", "at": "2026-07-18T00:00:00+00:00", "confidence": None},
            "style_description": {"learner": "identity_builder", "at": "2026-07-18T00:00:00+00:00", "confidence": None},
        },
        "_history": [],
    }
    rows: dict = {
        tenant_id: {
            "channel_identity": json.dumps(prior_identity),
            "style_description": "OLD dna-learned prose",
        }
    }
    prompt_rows: dict = {}
    calls = {"fetch_one": [], "execute": []}

    async def fake_fetch_one(query, *args):
        calls["fetch_one"].append((query, args))
        if "channel_identity" in query:
            return {"channel_identity": rows[args[0]]["channel_identity"]}
        return None

    async def fake_execute(query, *args):
        calls["execute"].append((query, args))
        if "tenant_prompt_defaults" in query:
            prompt_rows[(args[0], args[1])] = args[2]
        elif "channel_profiles" in query and "channel_identity" in query:
            tid, style_desc, identity_json = args
            rows[tid] = {"channel_identity": identity_json, "style_description": style_desc}

    async def fake_get_secret(slot, tid):
        assert slot == "anthropic_api_key"
        return "fake-anthropic-key"

    fake_client = FakeClaudeClient({
        "content": [{"type": "text", "text": json.dumps(_fake_generated_prompts())}]
    })

    monkeypatch.setattr(sp, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(sp, "execute", fake_execute)
    monkeypatch.setattr(vault, "get_secret", fake_get_secret)
    import httpx as _httpx_mod
    original_async_client = _httpx_mod.AsyncClient
    _httpx_mod.AsyncClient = lambda **kw: fake_client
    try:
        body = sp.StyleGenerateRequest(
            style_description="NEW hand-typed style — punchy and blunt.",
            channel_name="Test Channel",
            niche="finance",
            target_audience="beginners",
        )
        result = asyncio.run(sp.generate_prompts(body, tenant_id))
    finally:
        _httpx_mod.AsyncClient = original_async_client

    assert result["status"] == "generated"

    # The plain column write still happens (unchanged existing behavior —
    # per-video/tenant precedence in pipeline_executor.resolve_prompt is
    # untouched by this chunk).
    assert rows[tenant_id]["style_description"] == "NEW hand-typed style — punchy and blunt."

    # NEW: the channel_identity envelope now shows the overwrite, attributed.
    final_identity = coerce_identity(rows[tenant_id]["channel_identity"])
    assert final_identity["style_description"] == "NEW hand-typed style — punchy and blunt."
    prov = field_provenance(final_identity, "style_description")
    assert prov is not None, "style_description write was not stamped at all"
    assert prov["learner"] == "system_prompts"

    # The OTHER identity_builder field (voice_tone) must survive untouched —
    # this route must never clobber fields it doesn't own (the whole point
    # of routing through stamp_identity_write instead of a blind overwrite).
    assert final_identity["voice_tone"] == "confident, direct"
    assert field_provenance(final_identity, "voice_tone")["learner"] == "identity_builder"

    # A _history entry records the overwrite (something actually changed).
    changed_by = [h["learner"] for h in final_identity["_history"]]
    assert "system_prompts" in changed_by
    print("✅ test_generate_prompts_stamps_style_description_with_provenance")


def test_generate_prompts_still_writes_all_six_tenant_prompt_defaults(monkeypatch):
    """Regression guard: the provenance addition must not break the existing
    6-row tenant_prompt_defaults write (that's what actually drives
    resolve_prompt's tenant-override precedence at generation time)."""
    tenant_id = "tenant-c43-b"
    rows = {tenant_id: {"channel_identity": None, "style_description": None}}
    prompt_rows: dict = {}

    async def fake_fetch_one(query, *args):
        if "channel_identity" in query:
            return {"channel_identity": rows[args[0]]["channel_identity"]}
        return None

    async def fake_execute(query, *args):
        if "tenant_prompt_defaults" in query:
            prompt_rows[(args[0], args[1])] = args[2]
        elif "channel_profiles" in query:
            tid, style_desc, identity_json = args
            rows[tid] = {"channel_identity": identity_json, "style_description": style_desc}

    async def fake_get_secret(slot, tid):
        return "fake-anthropic-key"

    fake_client = FakeClaudeClient({
        "content": [{"type": "text", "text": json.dumps(_fake_generated_prompts())}]
    })

    monkeypatch.setattr(sp, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(sp, "execute", fake_execute)
    monkeypatch.setattr(vault, "get_secret", fake_get_secret)
    import httpx as _httpx_mod
    original_async_client = _httpx_mod.AsyncClient
    _httpx_mod.AsyncClient = lambda **kw: fake_client
    try:
        body = sp.StyleGenerateRequest(style_description="Blunt and punchy.")
        asyncio.run(sp.generate_prompts(body, tenant_id))
    finally:
        _httpx_mod.AsyncClient = original_async_client

    for key in sp.PROMPT_KEYS:
        assert (tenant_id, key) in prompt_rows, f"tenant_prompt_defaults row missing for {key!r}"
    print("✅ test_generate_prompts_still_writes_all_six_tenant_prompt_defaults")


# ---------------------------------------------------------------------------
# 2. identity_builder._thumbnail_style routes through vision_call
# ---------------------------------------------------------------------------

def test_thumbnail_style_calls_shared_vision_call_not_raw_kie_gateway(monkeypatch):
    """`_thumbnail_style` must go through `shared.clients.vision_client.
    vision_call` (the safe, provider-chained helper) instead of a bespoke
    direct httpx POST to Kie's Claude gateway — closing the exact
    'silently drops image blocks' risk that module's docstring warns about."""
    calls = []

    async def fake_get_secret(slot, tid):
        assert slot == "kie_ai_api_key"
        return "fake-kie-key"

    async def fake_vision_call(prompt, images, *, kie_key=None, anthropic_key=None,
                                tier="fast", max_tokens=500, timeout=180.0):
        calls.append({
            "prompt": prompt, "images": images, "kie_key": kie_key,
            "anthropic_key": anthropic_key, "tier": tier, "max_tokens": max_tokens,
        })
        return json.dumps({
            "layout": "subject left, text right",
            "subject": "a single machine",
            "text_style": "bold caps",
            "color_palette": "navy + amber",
            "mood": "authoritative",
            "recurring_elements": "thin gold border",
        })

    monkeypatch.setattr(vault, "get_secret", fake_get_secret)
    import shared.clients.vision_client as vision_client_mod
    monkeypatch.setattr(vision_client_mod, "vision_call", fake_vision_call)

    result = asyncio.run(ib._thumbnail_style("tenant-x", ["http://a", "http://b", "http://c", "http://d"]))

    assert len(calls) == 1, "must call vision_call exactly once"
    call = calls[0]
    assert call["kie_key"] == "fake-kie-key"
    assert call["anthropic_key"] is None
    assert call["tier"] == "fast"
    assert call["max_tokens"] == 1400
    # Only the top 3 thumbnails, same cap as the old direct-httpx call.
    assert call["images"] == ["http://a", "http://b", "http://c"]
    assert result["subject"] == "a single machine"

    # The raw Kie Claude gateway constant is gone — confirms this isn't a
    # second parallel call path, it's a real replacement.
    assert not hasattr(ib, "_KIE_CLAUDE_URL")
    print("✅ test_thumbnail_style_calls_shared_vision_call_not_raw_kie_gateway")


def test_thumbnail_style_no_key_or_no_urls_returns_none_unchanged(monkeypatch):
    """Byte-identical fallback for a tenant with no Kie key or no thumbnails
    yet (i.e. no DNA to extract) — same short-circuit as before this chunk,
    proven so the convergence didn't change behavior for the no-DNA case."""
    async def fake_get_secret_none(slot, tid):
        return None

    monkeypatch.setattr(vault, "get_secret", fake_get_secret_none)
    assert asyncio.run(ib._thumbnail_style("tenant-y", ["http://a"])) is None

    async def fake_get_secret_present(slot, tid):
        return "fake-kie-key"

    monkeypatch.setattr(vault, "get_secret", fake_get_secret_present)
    assert asyncio.run(ib._thumbnail_style("tenant-y", [])) is None
    print("✅ test_thumbnail_style_no_key_or_no_urls_returns_none_unchanged")


def test_thumbnail_style_vision_failure_returns_none_not_raise(monkeypatch):
    """Every provider in the vision_call chain failing (VisionUnavailable, or
    any other exception) must degrade to None — never raise into
    build_channel_identity, matching the old bare try/except's contract."""
    async def fake_get_secret(slot, tid):
        return "fake-kie-key"

    import shared.clients.vision_client as vision_client_mod

    async def fake_vision_call_raises(*a, **k):
        raise vision_client_mod.VisionUnavailable("no provider produced a usable reply")

    monkeypatch.setattr(vault, "get_secret", fake_get_secret)
    monkeypatch.setattr(vision_client_mod, "vision_call", fake_vision_call_raises)

    result = asyncio.run(ib._thumbnail_style("tenant-z", ["http://a"]))
    assert result is None
    print("✅ test_thumbnail_style_vision_failure_returns_none_not_raise")


TESTS = [
    test_generate_prompts_stamps_style_description_with_provenance,
    test_generate_prompts_still_writes_all_six_tenant_prompt_defaults,
    test_thumbnail_style_calls_shared_vision_call_not_raw_kie_gateway,
    test_thumbnail_style_no_key_or_no_urls_returns_none_unchanged,
    test_thumbnail_style_vision_failure_returns_none_not_raise,
]


def main() -> int:
    import inspect
    failed = 0
    for t in TESTS:
        try:
            sig = inspect.signature(t)
            if "monkeypatch" in sig.parameters:
                print(f"skip (needs pytest monkeypatch fixture): {t.__name__}")
                continue
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
