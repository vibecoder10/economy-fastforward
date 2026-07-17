"""Unit tests for shared.clients.image_model_router — the ONE resolver that
turns a video's `image_model_override` into an actual ImageClient call,
shared by storyengine/backend/scripts/coverage_to_app.py (redo_characters,
generate_storyboard_sheet_for_scene, redraw_asset_image) and the legacy
pipeline_executor.py `run_image_variants` path.

No network: a FakeImageClient records which method was called with which
args instead of hitting Kie. See storyengine-wiring-fix-checklist.md §0.1
("the Pictures model select writes image_model_override, but the live path
ignores it") — these tests are the trace-level proof that the override now
reaches the generation call, AND that the untouched default (no override)
path calls the exact same methods with the exact same arguments as before
this fix (so existing videos render byte-identically).
"""
import asyncio

from shared.clients.image_model_router import (
    VALID_IMAGE_MODELS,
    generate_scene_image_for_model,
)


class FakeImageClient:
    """Records every call; `plan` maps method name -> return value (or a list
    of return values consumed in order, for methods called more than once)."""

    SCENE_MODEL = "nano-banana-2"  # mirrors ImageClient.SCENE_MODEL

    def __init__(self, plan: dict):
        self.plan = dict(plan)
        self.calls: list[tuple[str, tuple, dict]] = []

    def _consume(self, name):
        val = self.plan.get(name)
        if isinstance(val, list):
            return val.pop(0) if val else None
        return val

    async def generate_scene_image_zimage(self, prompt, aspect_ratio="16:9"):
        self.calls.append(("generate_scene_image_zimage", (prompt,), {"aspect_ratio": aspect_ratio}))
        return self._consume("generate_scene_image_zimage")

    async def generate_with_reference(self, prompt, reference_image_url, aspect_ratio="16:9", resolution="1K"):
        self.calls.append(("generate_with_reference", (prompt, reference_image_url),
                            {"aspect_ratio": aspect_ratio}))
        return self._consume("generate_with_reference")

    async def generate_and_wait(self, prompt, aspect_ratio="16:9", model=None):
        self.calls.append(("generate_and_wait", (prompt,), {"aspect_ratio": aspect_ratio, "model": model}))
        urls = self._consume("generate_and_wait")
        return urls

    async def generate_thumbnail_gpt2(self, prompt, reference_image_url, aspect_ratio="16:9", resolution="2K"):
        self.calls.append(("generate_thumbnail_gpt2", (prompt, reference_image_url),
                            {"aspect_ratio": aspect_ratio, "resolution": resolution}))
        return self._consume("generate_thumbnail_gpt2")

    async def generate_scene_image_gpt(self, prompt, reference_image_url, aspect_ratio="16:9", resolution="2K"):
        self.calls.append(("generate_scene_image_gpt", (prompt, reference_image_url),
                            {"aspect_ratio": aspect_ratio, "resolution": resolution}))
        return self._consume("generate_scene_image_gpt")


def _run(coro):
    return asyncio.run(coro)


def test_valid_image_models_matches_known_good_values():
    # The exact 3 values the Pictures selector writes (ScenesWorkspaceTab L1121-1126).
    assert VALID_IMAGE_MODELS == {"nano-banana-2", "gpt-image-2", "z-image"}


# --- default / unset / 'gpt-image-2' override: the PRE-EXISTING behavior, unchanged ---

def test_default_no_override_with_refs_calls_gpt_thumbnail_unchanged():
    """This is byte-for-byte what coverage_to_app.py's 3 call sites did before this
    fix: `generate_thumbnail_gpt2(prompt, refs, aspect, resolution=resolution)`."""
    ic = FakeImageClient({"generate_thumbnail_gpt2": {"url": "https://img/gpt.png", "model": "gpt-image-2"}})
    url, model = _run(generate_scene_image_for_model(
        ic, None, "a prompt", reference_urls=["ref1", "ref2"], aspect_ratio="16:9", resolution="2K"))
    assert url == "https://img/gpt.png"
    assert model == "gpt-image-2"
    assert ic.calls == [("generate_thumbnail_gpt2", ("a prompt", ["ref1", "ref2"]),
                          {"aspect_ratio": "16:9", "resolution": "2K"})]


def test_default_no_override_without_refs_calls_gpt_text_to_image_unchanged():
    """No refs -> generate_scene_image_gpt(prompt, None, aspect, resolution=resolution),
    matching the pre-existing hardcoded call exactly."""
    ic = FakeImageClient({"generate_scene_image_gpt": {"url": "https://img/gpt2.png", "model": "gpt-image-2"}})
    url, model = _run(generate_scene_image_for_model(ic, "", "a prompt", aspect_ratio="16:9"))
    assert url == "https://img/gpt2.png"
    assert model == "gpt-image-2"
    assert ic.calls == [("generate_scene_image_gpt", ("a prompt", None), {"aspect_ratio": "16:9", "resolution": "2K"})]


def test_gpt_image_2_explicit_override_behaves_like_default():
    ic = FakeImageClient({"generate_scene_image_gpt": {"url": "https://img/gpt3.png", "model": "gpt-image-2"}})
    url, model = _run(generate_scene_image_for_model(ic, "gpt-image-2", "p", aspect_ratio="16:9"))
    assert (url, model) == ("https://img/gpt3.png", "gpt-image-2")


def test_default_path_surfaces_internal_gpt_to_nano_fallback_truthfully():
    """generate_scene_image_gpt can itself silently fall back to nano-banana-2 on a
    content-policy block; the resolver must report the TRUE model, not assume gpt."""
    ic = FakeImageClient({"generate_scene_image_gpt": {"url": "https://img/nano-fallback.png", "model": "nano-banana-2"}})
    url, model = _run(generate_scene_image_for_model(ic, None, "p", aspect_ratio="16:9"))
    assert (url, model) == ("https://img/nano-fallback.png", "nano-banana-2")


def test_unrecognized_override_falls_back_to_default_gpt_path():
    ic = FakeImageClient({"generate_scene_image_gpt": {"url": "https://img/x.png", "model": "gpt-image-2"}})
    url, model = _run(generate_scene_image_for_model(ic, "made-up-model", "p", aspect_ratio="16:9"))
    assert (url, model) == ("https://img/x.png", "gpt-image-2")


# --- 'z-image' override ---

def test_zimage_override_success_never_touches_gpt():
    ic = FakeImageClient({"generate_scene_image_zimage": {"url": "https://img/z.png"}})
    url, model = _run(generate_scene_image_for_model(
        ic, "z-image", "p", reference_urls=["ref1"], aspect_ratio="9:16"))
    assert (url, model) == ("https://img/z.png", "z-image")
    assert [c[0] for c in ic.calls] == ["generate_scene_image_zimage"]
    assert ic.calls[0][2]["aspect_ratio"] == "9:16"


def test_zimage_override_falls_back_to_gpt_on_failure():
    ic = FakeImageClient({
        "generate_scene_image_zimage": None,  # z-image failed
        "generate_thumbnail_gpt2": {"url": "https://img/fallback.png", "model": "gpt-image-2"},
    })
    url, model = _run(generate_scene_image_for_model(
        ic, "z-image", "p", reference_urls=["ref1"], aspect_ratio="16:9"))
    assert (url, model) == ("https://img/fallback.png", "gpt-image-2")
    assert [c[0] for c in ic.calls] == ["generate_scene_image_zimage", "generate_thumbnail_gpt2"]


# --- 'nano-banana-2' override ---

def test_nano_override_with_refs_uses_generate_with_reference():
    ic = FakeImageClient({"generate_with_reference": {"url": "https://img/nano.png"}})
    url, model = _run(generate_scene_image_for_model(
        ic, "nano-banana-2", "p", reference_urls=["ref1", "ref2"], aspect_ratio="16:9"))
    assert (url, model) == ("https://img/nano.png", "nano-banana-2")
    assert ic.calls[0][0] == "generate_with_reference"
    assert ic.calls[0][1] == ("p", ["ref1", "ref2"])


def test_nano_override_without_refs_uses_generate_and_wait_with_scene_model():
    # generate_and_wait itself returns a list[str] of URLs — wrap it in an extra
    # list so FakeImageClient's "list = sequence of per-call return values"
    # convention pops that whole list back out for the single call made here.
    ic = FakeImageClient({"generate_and_wait": [["https://img/nano2.png"]]})
    url, model = _run(generate_scene_image_for_model(ic, "nano-banana-2", "p", aspect_ratio="16:9"))
    assert (url, model) == ("https://img/nano2.png", "nano-banana-2")
    assert ic.calls[0] == ("generate_and_wait", ("p",), {"aspect_ratio": "16:9", "model": "nano-banana-2"})


def test_nano_override_falls_back_to_gpt_on_failure():
    ic = FakeImageClient({
        "generate_with_reference": None,
        "generate_thumbnail_gpt2": {"url": "https://img/fallback2.png", "model": "gpt-image-2"},
    })
    url, model = _run(generate_scene_image_for_model(
        ic, "nano-banana-2", "p", reference_urls=["ref1"], aspect_ratio="16:9"))
    assert (url, model) == ("https://img/fallback2.png", "gpt-image-2")
    assert [c[0] for c in ic.calls] == ["generate_with_reference", "generate_thumbnail_gpt2"]


def test_every_attempt_failing_returns_none_none():
    ic = FakeImageClient({"generate_scene_image_zimage": None, "generate_scene_image_gpt": None})
    url, model = _run(generate_scene_image_for_model(ic, "z-image", "p", aspect_ratio="16:9"))
    assert (url, model) == (None, None)
