"""Tests for C21b (checklist §2.1 [U]/[B], P2.1b part 2 — "delete the
duplicated preset lists + producer/chat backend sourcing + chat gallery
card").

C21a discovered a real entanglement before this chunk could touch anything:
producer_prompt.VISUAL_PRESETS served TWO unrelated vocabularies — (a) the
chat LOOK card's style-DESCRIPTION options (pixar_3d/flat_2d/realistic/anime/
watercolor/comic — a free-text aesthetic overlay) and (b) the reference-video
vision classifier's ANIMATION-MEDIUM vocabulary (routes/chat.py's
_detect_reference_style_preset / _annotate_style_recommendation) — the SAME
six ids, but answering a different question with no valid mapping to the 5
`style_presets` ENGINE rows (holographic_hud, clay_mannequin, ...).

This chunk: (1) moves that six-entry dict to channel_format.STYLE_DESCRIPTIONS
— the ONE source for the classifier, routes/chat.py's _spec_to_create_request,
routes/projects.py's _channel_style_dna, and the new GET /api/style-
descriptions endpoint; (2) deletes producer_prompt.VISUAL_PRESETS entirely
(grep-proof: zero remaining readers); (3) adds an ADDITIVE style_preset_id
axis to the chat LOOK flow (a NEW optional "look_engine" card, backed by the
live style_presets table via a fail-soft _style_presets_brief, sourcing
CreateVideoRequest.style_preset_id directly — a SEPARATE, complementary axis
from the style-description mapping, not a replacement of it).

Layers pinned here, no live DB / no network:
  1. channel_format.STYLE_DESCRIPTIONS exists with the right shape; producer_
     prompt.VISUAL_PRESETS is gone.
  2. GET /api/style-descriptions returns the 6-entry catalog in fixed order.
  3. routes.chat._detect_reference_style_preset / _annotate_style_
     recommendation genuinely read channel_format.STYLE_DESCRIPTIONS at call
     time (proven via monkeypatching that dict to a distinctive value — a
     hardcoded-copy regression would NOT pick up the monkeypatch and this
     test would fail).
  4. routes.chat._spec_to_create_request: axis-B mapping (visual_style /
     visual_style_label / image_style_override) unchanged; NEW style_
     preset_id passthrough, additive and independent.
  5. routes.chat._handle_approve's selections merge for the new "look_engine"
     card selection.
  6. routes.chat._style_presets_brief: real rows path + fail-soft fallback
     (DB error, and empty-table) — never raises, never empty.
  7. routes.projects._channel_style_dna reads channel_format.STYLE_
     DESCRIPTIONS (not producer_prompt).
  8. Grep-proof: zero `VISUAL_PRESETS` readers left in backend .py source
     (excluding historical comments naming the old identifier).

Same stub pattern as test_c15c_director_memory.py: no live DB, no network.
Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c21b_style_axis_split.py -q
"""
import asyncio
import glob
import os
import re
import sys
import types

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom, safe_column=lambda name: name)
_stub("vault", get_secret=_boom)

import channel_format  # noqa: E402
import producer_prompt  # noqa: E402
import routes.chat as chat  # noqa: E402
import routes.projects as projects  # noqa: E402
import routes.style_descriptions as style_descriptions_route  # noqa: E402

TENANT = "tenant-1"

_SIX_IDS = {"pixar_3d", "flat_2d", "realistic", "anime", "watercolor", "comic"}


# =============================================================================
# 1. channel_format.STYLE_DESCRIPTIONS exists; producer_prompt.VISUAL_PRESETS
#    is gone
# =============================================================================

def test_style_descriptions_has_all_six_ids_with_label_and_look():
    assert set(channel_format.STYLE_DESCRIPTIONS.keys()) == _SIX_IDS
    for pid, v in channel_format.STYLE_DESCRIPTIONS.items():
        assert v.get("label"), pid
        assert v.get("look"), pid


def test_producer_prompt_no_longer_defines_visual_presets():
    assert not hasattr(producer_prompt, "VISUAL_PRESETS")


def test_producer_system_prompt_mentions_look_engine_and_style_preset_id():
    """The optional LOOK ENGINE card + spec.style_preset_id field must be
    taught in the prompt text itself (not just wired in code) — a card the
    model was never told to emit never gets emitted."""
    assert "look_engine" in producer_prompt.PRODUCER_SYSTEM_PROMPT
    assert "style_preset_id" in producer_prompt.PRODUCER_SYSTEM_PROMPT


# =============================================================================
# 2. GET /api/style-descriptions
# =============================================================================

def test_style_descriptions_endpoint_returns_six_in_fixed_order():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth import get_tenant_id

    app = FastAPI()
    app.include_router(style_descriptions_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: "00000000-0000-0000-0000-000000000000"
    client = TestClient(app)

    resp = client.get("/api/style-descriptions")
    assert resp.status_code == 200
    body = resp.json()
    descs = body["descriptions"]
    ids = [d["id"] for d in descs]
    assert ids == list(channel_format.STYLE_DESCRIPTIONS.keys())
    assert set(ids) == _SIX_IDS
    first = descs[0]
    assert first["label"] == channel_format.STYLE_DESCRIPTIONS[first["id"]]["label"]
    assert first["look"] == channel_format.STYLE_DESCRIPTIONS[first["id"]]["look"]


def test_style_descriptions_endpoint_requires_tenant_auth():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(style_descriptions_route.router)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/style-descriptions")
    assert resp.status_code in (401, 403, 422)


# =============================================================================
# 3. The vision classifier genuinely reads channel_format.STYLE_DESCRIPTIONS
#    at call time (not a frozen/hardcoded copy)
# =============================================================================

def test_detect_reference_style_preset_reads_live_channel_format_dict(monkeypatch):
    """Monkeypatch STYLE_DESCRIPTIONS to a distinctive, non-standard id and
    prove the classifier picks it up — a regression that re-hardcodes the six
    ids inline inside chat.py (instead of importing channel_format's dict)
    would NOT see this monkeypatch and this test would fail."""
    fake_ids = {"totally_custom_medium": {"label": "Custom", "look": "n/a"}}
    monkeypatch.setattr(channel_format, "STYLE_DESCRIPTIONS", fake_ids)

    fake_model_video = types.ModuleType("routes.model_video")
    fake_model_video._parse_youtube_id = lambda url: "abc123"
    fake_model_video._scene_frame_urls = lambda yid: ["frame1.jpg"]
    monkeypatch.setitem(sys.modules, "routes.model_video", fake_model_video)

    async def fake_vision_call(prompt, frames, anthropic_key=None, tier=None, max_tokens=None):
        return "this looks like totally_custom_medium to me"
    fake_vision = types.ModuleType("shared.clients.vision_client")
    fake_vision.vision_call = fake_vision_call
    monkeypatch.setitem(sys.modules, "shared.clients.vision_client", fake_vision)

    async def fake_get_secret(slot, tenant_id):
        return "sk-ant-test"
    monkeypatch.setattr(chat, "get_secret", fake_get_secret)

    state = {}
    result = asyncio.run(chat._detect_reference_style_preset(TENANT, "https://youtu.be/abc123", state))
    assert result == "totally_custom_medium"
    # Cached in state per reference (unchanged behavior).
    assert state["_ref_style_preset"] == "totally_custom_medium"


def test_detect_reference_style_preset_no_match_falls_back_to_none(monkeypatch):
    fake_model_video = types.ModuleType("routes.model_video")
    fake_model_video._parse_youtube_id = lambda url: "abc123"
    fake_model_video._scene_frame_urls = lambda yid: ["frame1.jpg"]
    monkeypatch.setitem(sys.modules, "routes.model_video", fake_model_video)

    async def fake_vision_call(prompt, frames, anthropic_key=None, tier=None, max_tokens=None):
        return "unrecognizable garbage"
    fake_vision = types.ModuleType("shared.clients.vision_client")
    fake_vision.vision_call = fake_vision_call
    monkeypatch.setitem(sys.modules, "shared.clients.vision_client", fake_vision)

    async def fake_get_secret(slot, tenant_id):
        return "sk-ant-test"
    monkeypatch.setattr(chat, "get_secret", fake_get_secret)

    state = {}
    result = asyncio.run(chat._detect_reference_style_preset(TENANT, "https://youtu.be/abc123", state))
    assert result is None


def test_annotate_style_recommendation_reads_live_channel_format_label(monkeypatch):
    """Same live-read proof for the label lookup used to badge the 'style'
    card's recommended option."""
    monkeypatch.setattr(channel_format, "STYLE_DESCRIPTIONS",
                         {"flat_2d": {"label": "TOTALLY CUSTOM LABEL", "look": "n/a"}})

    async def fake_detect(tenant_id, ref, state):
        return "flat_2d"
    monkeypatch.setattr(chat, "_detect_reference_style_preset", fake_detect)

    data = {
        "plan": {"spec": {"reference_url": "https://youtu.be/xyz"}},
        "cards": [{"id": "style", "options": []}],
    }
    state = {"pending_reference_url": "https://youtu.be/xyz"}
    asyncio.run(chat._annotate_style_recommendation(data, TENANT, state))
    card = data["cards"][0]
    assert card["recommended_value"] == "flat_2d"
    assert "TOTALLY CUSTOM LABEL" in card["recommended_hint"]
    assert data["plan"]["spec"]["detected_style_label"] == "TOTALLY CUSTOM LABEL"


def test_annotate_style_recommendation_noop_when_creator_already_picked():
    data = {
        "plan": {"spec": {"reference_url": "https://youtu.be/xyz", "visual_style": "anime"}},
        "cards": [{"id": "style", "options": []}],
    }
    state = {"pending_reference_url": "https://youtu.be/xyz"}
    asyncio.run(chat._annotate_style_recommendation(data, TENANT, state))
    assert "recommended_value" not in data["cards"][0]


# =============================================================================
# 4. _spec_to_create_request — axis-B mapping unchanged, style_preset_id
#    additive
# =============================================================================

def test_spec_to_create_request_maps_style_description_preset_unchanged():
    spec = {"title": "My Video", "visual_style": "pixar_3d", "video_length_minutes": 5}
    req = chat._spec_to_create_request(spec)
    assert req.visual_style == "pixar_3d"
    assert req.visual_style_label == "Pixar 3D"
    assert "Pixar-style CG" in req.image_style_override
    assert req.style_preset_id is None


def test_spec_to_create_request_passes_through_style_preset_id():
    spec = {"title": "My Video", "style_preset_id": "holographic_hud", "video_length_minutes": 5}
    req = chat._spec_to_create_request(spec)
    assert req.style_preset_id == "holographic_hud"
    # Axis B untouched/independent when only the engine axis is picked.
    assert req.visual_style is None


def test_spec_to_create_request_both_axes_together():
    """The two axes are independent and additive — picking one never clobbers
    the other (checklist §C21b's core invariant)."""
    spec = {
        "title": "My Video", "visual_style": "anime",
        "style_preset_id": "clay_mannequin", "video_length_minutes": 5,
    }
    req = chat._spec_to_create_request(spec)
    assert req.visual_style == "anime"
    assert req.style_preset_id == "clay_mannequin"


def test_spec_to_create_request_blank_style_preset_id_is_none():
    spec = {"title": "My Video", "style_preset_id": "   ", "video_length_minutes": 5}
    req = chat._spec_to_create_request(spec)
    assert req.style_preset_id is None


# =============================================================================
# 5. _handle_approve's selections merge for the new "look_engine" card
# =============================================================================

def test_handle_approve_selections_merge_includes_look_engine():
    """Source-level lock: the selections-merge block in _handle_approve must
    read selections['look_engine'] into spec['style_preset_id'], mirroring
    the pre-existing 'style' -> visual_style merge exactly."""
    import inspect
    src = inspect.getsource(chat._handle_approve)
    assert 'selections.get("look_engine")' in src
    assert '"style_preset_id": selections["look_engine"]' in src


# =============================================================================
# 6. _style_presets_brief — real rows + fail-soft fallback
# =============================================================================

def test_style_presets_brief_real_rows(monkeypatch):
    async def fake_fetch_all(query, *a):
        assert "style_presets" in query
        assert "active = true" in query
        return [
            {"id": "neutral_v1", "display_name": "Neutral Documentary (default)", "description": None},
            {"id": "holographic_hud", "display_name": "Holographic Intelligence Display", "description": "war room aesthetic"},
        ]
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    brief = asyncio.run(chat._style_presets_brief(TENANT))
    assert "LOOK ENGINE PRESETS" in brief
    assert '"neutral_v1": Neutral Documentary (default)' in brief
    assert '"holographic_hud": Holographic Intelligence Display — war room aesthetic' in brief


def test_style_presets_brief_fail_soft_on_db_error(monkeypatch):
    async def fake_fetch_all(*a, **k):
        raise RuntimeError("db is down")
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    brief = asyncio.run(chat._style_presets_brief(TENANT))
    assert "LOOK ENGINE PRESETS" in brief
    assert "neutral_v1" in brief  # frozen minimal default, never crashes


def test_style_presets_brief_fail_soft_on_empty_table(monkeypatch):
    async def fake_fetch_all(*a, **k):
        return []
    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    brief = asyncio.run(chat._style_presets_brief(TENANT))
    assert "LOOK ENGINE PRESETS" in brief
    assert "neutral_v1" in brief


def test_style_presets_brief_wired_into_both_producer_entry_points():
    """Source-lock: both _seed_producer and chat_turn's intake turn actually
    call _style_presets_brief (a helper that exists but is never called is
    dead code)."""
    import inspect
    assert "_style_presets_brief(tenant_id)" in inspect.getsource(chat._seed_producer)
    assert "_style_presets_brief(tenant_id)" in inspect.getsource(chat.chat_turn)


# =============================================================================
# 7. routes/projects.py's _channel_style_dna reads channel_format, not
#    producer_prompt
# =============================================================================

def test_channel_style_dna_source_reads_channel_format_not_producer_prompt():
    import inspect
    src = inspect.getsource(projects._channel_style_dna)
    assert "from channel_format import STYLE_DESCRIPTIONS" in src
    assert "producer_prompt" not in src


# =============================================================================
# 8. Grep-proof: zero VISUAL_PRESETS readers left (excluding comments naming
#    the old identifier for history)
# =============================================================================

_REAL_USAGE = re.compile(r"import\s+VISUAL_PRESETS\b|VISUAL_PRESETS\.\w|VISUAL_PRESETS\[|VISUAL_PRESETS\s*=")


def test_grep_proof_zero_visual_presets_readers():
    """Zero actual code references (import / attribute access / definition)
    to the retired producer_prompt.VISUAL_PRESETS — bare prose/comments
    naming the old identifier for history are fine (channel_format.py,
    producer_prompt.py, routes/chat.py, routes/style_descriptions.py all
    mention it that way deliberately)."""
    backend_root = os.path.abspath(_BACKEND)
    offenders = []
    for path in glob.glob(os.path.join(backend_root, "**", "*.py"), recursive=True):
        if "/venv/" in path or "/__pycache__/" in path or path.endswith("test_c21b_style_axis_split.py"):
            continue
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if _REAL_USAGE.search(line):
                    offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert not offenders, "VISUAL_PRESETS readers still present:\n" + "\n".join(offenders)


def test_grep_proof_frontend_visual_presets_file_deleted():
    frontend_root = os.path.abspath(os.path.join(_BACKEND, "..", "frontend"))
    path = os.path.join(frontend_root, "src", "lib", "visual-presets.ts")
    assert not os.path.exists(path)


def test_grep_proof_zero_frontend_code_readers_of_deleted_module():
    frontend_src = os.path.abspath(os.path.join(_BACKEND, "..", "frontend", "src"))
    offenders = []
    for path in glob.glob(os.path.join(frontend_src, "**", "*.ts*"), recursive=True):
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if re.search(r'from ["\']@/lib/visual-presets["\']', line):
                    offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert not offenders, "still importing the deleted visual-presets module:\n" + "\n".join(offenders)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
