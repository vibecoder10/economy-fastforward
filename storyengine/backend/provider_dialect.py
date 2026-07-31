"""D13-1: the provider-dialect adapter for clip generation.

A July audit found that generator independence is real at the ROUTING layer
(one ``MODEL_REGISTRY`` + ``resolve_clip_model``/``dialect_for_model``) but
each provider's PROMPT DIALECT was baked straight into creative code:
``pipeline_executor.py``'s ``_animate_for``/``_decorate`` hardcoded Grok's
``@image1``/``@image2`` reference-token syntax into shot prompt TEXT, and
the inline Veo branch bypassed ``_decorate`` entirely, sending a raw prompt
through a different kwarg shape (``image_url=`` instead of a positional
image arg, no ``duration``/``extra_image_urls``/``resolution``). Swapping
which engine a shot uses meant touching creative code.

This module is the fix: ONE adapter. Creative code (``pipeline_executor.py``)
builds a NEUTRAL, provider-agnostic request — the prompt text it already
composed (motion-guard prefix, camera-preset override, no-speech clause —
none of that is a provider concern and none of it moves here), the ordered
reference-image slots, and the motion/duration params — and hands it to
``build_call()`` along with the model id. The adapter returns the
PROVIDER-SHAPED call: the final prompt string (decorated with whatever
inline token syntax that provider needs, or left raw) plus the kwargs dict
shaped for that provider's client method.

``shared/clients/image_client.py`` still EXECUTES the call — this module
only shapes the request handed to it. Swapping engines is now a routing
decision with zero creative-code changes.

PURE REFACTOR (D13-1): every function here is behavior-for-behavior moved
from ``pipeline_executor.py``'s ``_animate_for``/``_decorate``/inline Veo
branch, not rewritten. See
``tests/functional/test_d13_1_provider_dialect_golden.py`` (end-to-end,
byte-identical prompt+kwargs through the real ``run_clip_generation``) and
``tests/functional/test_provider_dialect.py`` (adapter-level unit tests)
for the proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Dialect classification — which provider "voice" a model id speaks.
# ---------------------------------------------------------------------------

def dialect_for_model(model_id: str) -> str:
    """Classify a model id into a dialect name: "veo", "seedance", or the
    "grok" fallback.

    Verbatim decision, moved from two call sites that used to duplicate it:
    ``_animate_for``'s ``mid.startswith("seedance")`` branch, and the
    inline clip-generation branch's ``row_model_id.startswith("veo-3.1")``
    check. Anything that isn't Veo or Seedance falls through to "grok" —
    exactly ``_animate_for``'s own fallthrough (its `else` branch runs for
    "grok-imagine" AND for any unrecognized id alike).
    """
    mid = model_id or ""
    if mid.startswith("veo-3.1"):
        return "veo"
    if mid.startswith("seedance"):
        return "seedance"
    return "grok"


# ---------------------------------------------------------------------------
# Neutral request / provider-shaped call
# ---------------------------------------------------------------------------

@dataclass
class ClipDialectRequest:
    """Neutral, provider-agnostic description of one shot to animate.

    Everything in here is already-composed, provider-AGNOSTIC creative
    output (motion-guard prefix, camera-preset override, no-speech clause,
    speaking-vs-narration prompt selection — none of that is a provider
    concern, none of it lives in this module). The adapter only decides how
    to WRAP ``core_prompt`` and how to SHAPE the call.
    """

    core_prompt: str
    image_url: str
    duration: float
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    # Ordered reference-image slots AFTER the primary image_url — today
    # this is at most one URL (the character reference sheet), matching
    # run_clip_generation._animate_recover's `extra = [_proxy_url(sheet)]
    # if sheet else None`.
    reference_image_urls: list = field(default_factory=list)
    # Grok-dialect decoration inputs — moved verbatim from _decorate's
    # closure over `cast_names`/`style_note`/`section_camera_mode`/
    # `section_exact_seconds`.
    cast_names: str = ""
    style_note: str = ""
    camera_mode: str = ""
    camera_seconds: Optional[int] = None
    # Veo-dialect inputs.
    veo_model: Optional[str] = None
    task_id_out: Optional[list] = None


@dataclass
class ClipDialectCall:
    """Provider-shaped call, ready to hand to shared.clients.image_client.

    ``method``: the client method name to invoke (``generate_video`` /
    ``generate_video_seedance`` / ``generate_video_veo``) — pipeline_executor
    still owns dispatching to the right client method (and to
    ``_animate_recover``'s content-policy retry, which only Grok/Seedance
    get — Veo's inline branch never had it); this module only shapes the
    prompt + kwargs that call gets.
    """

    method: str
    prompt: str
    kwargs: dict


# ---------------------------------------------------------------------------
# Grok dialect — @imageN reference-token decoration.
# ---------------------------------------------------------------------------

def decorate_grok_prompt(
    core_prompt: str,
    *,
    has_reference_sheet: bool,
    cast_names: str = "",
    style_note: str = "",
    camera_mode: str = "",
    camera_seconds: Optional[int] = None,
) -> str:
    """Grok's @imageN reference-token dialect.

    Moved VERBATIM from pipeline_executor.py's ``_decorate`` (pre-D13-1):
    @image1 is the ground truth for the shot, and the constraints LEAD the
    prompt (early instructions win — Grok would otherwise invent an
    off-screen character on a panel that doesn't show them). Also used for
    the "seedance" dialect below — Seedance shares this exact decoration
    (only its call's kwarg shape differs from Grok's)."""
    p = ("Animate @image1 exactly as shown: same characters, same faces, ages,"
         " heights, proportions and clothing. NEVER introduce a character who"
         " is not visible in @image1 — if someone is off-screen, only hands or"
         " feet may enter the frame.")
    if has_reference_sheet:
        p += (f" @image2 is the official cast sheet"
              + (f" ({cast_names})" if cast_names else "")
              + " — anyone visible in @image1 must match it precisely.")
    if style_note:
        p += f" Art style: {style_note}"
    p += f" Motion: {core_prompt}"
    if camera_mode:
        p += (
            f" Use the approved {camera_mode} camera grammar "
            f"for this exact {camera_seconds}-second section."
        )
    return p


# ---------------------------------------------------------------------------
# The ONE adapter entry point.
# ---------------------------------------------------------------------------

def build_call(model_id: str, request: ClipDialectRequest) -> ClipDialectCall:
    """model_id + neutral request -> provider-shaped call.

    Grok and Seedance share the SAME @imageN decoration (moved from
    ``_decorate``, called uniformly for both in pre-D13-1
    ``run_clip_generation._one`` regardless of which of the two
    ``_animate_for(mid)`` picked) but differ in kwarg shape: Grok's
    ``generate_video`` takes ``resolution``, Seedance's
    ``generate_video_seedance`` does not. Veo skips decoration entirely —
    RAW prompt — and its kwarg shape has neither ``duration`` nor
    ``extra_image_urls``; it takes ``image_url``/``model`` instead (moved
    verbatim from the inline ``if row_model_id.startswith("veo-3.1")``
    branch)."""
    dialect = dialect_for_model(model_id)
    extra_image_urls = list(request.reference_image_urls) or None

    if dialect == "veo":
        return ClipDialectCall(
            method="generate_video_veo",
            prompt=request.core_prompt,  # RAW — no @image1/@image2 wrapper
            kwargs={
                "image_url": request.image_url,
                "model": request.veo_model,
                "task_id_out": request.task_id_out,
            },
        )

    final_prompt = decorate_grok_prompt(
        request.core_prompt,
        has_reference_sheet=bool(request.reference_image_urls),
        cast_names=request.cast_names,
        style_note=request.style_note,
        camera_mode=request.camera_mode,
        camera_seconds=request.camera_seconds,
    )

    if dialect == "seedance":
        return ClipDialectCall(
            method="generate_video_seedance",
            prompt=final_prompt,
            kwargs={
                "duration": request.duration,
                "extra_image_urls": extra_image_urls,
                "aspect_ratio": request.aspect_ratio,
                "task_id_out": request.task_id_out,
            },
        )

    # "grok" — the default fallback dialect.
    return ClipDialectCall(
        method="generate_video",
        prompt=final_prompt,
        kwargs={
            "duration": request.duration,
            "extra_image_urls": extra_image_urls,
            "aspect_ratio": request.aspect_ratio,
            "resolution": request.resolution,
            "task_id_out": request.task_id_out,
        },
    )
