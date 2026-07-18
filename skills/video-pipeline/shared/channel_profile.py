"""
Channel Profile — defines the cinematic and editorial identity for a channel.

This is used by the storyboard_bot to drive the Cinematic Directive Generator.
It controls HOW the AI director plans shots: visual style, lens choices, color
grading, character handling, emotional arc templates, and shot requirements.

This is SEPARATE from visual_profiles/ which controls image prompt construction
(prefixes, suffixes, substyles, rotation). Channel profile is the DIRECTOR's
brief; visual profile is the ARTIST's palette.

For now, EFF profile is the default. Future: load per-tenant from config or Airtable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from shared.profiles.visual import get_profile_or_default as load_visual_profile


@dataclass
class LensProfile:
    """Camera and lens behavior for shot planning."""
    focal_range: str = "24-85mm"
    dof_tendency: str = (
        "medium — deeper in establishing wides, shallower in character close-ups"
    )
    movement_vocabulary: list[str] = field(default_factory=lambda: [
        "slow push-in for tension building",
        "lateral track for reveals",
        "subtle orbit for emphasis",
        "static lock-off for impact moments",
        "gentle handheld micro-shake for urgency/chaos",
    ])
    shutter_feel: str = "cinematic — smooth motion blur, deliberate pacing"
    grain: str = "subtle organic film grain, warm texture"


@dataclass
class ColorGrade:
    """Lighting and color grading direction. Style-agnostic by default — the
    palette is whatever the video's visual style and reference images call for,
    NOT a fixed channel look."""
    primary_palette: str = (
        "no fixed palette — follow the video's visual style and the attached "
        "reference images; use colors that fit the scene and the channel's look"
    )
    contrast: str = "contrast appropriate to the visual style and the scene's mood"
    shadow_treatment: str = "shadows with visible detail, never crushed"
    highlight_treatment: str = "motivated lighting that reads the subject clearly"
    material_priorities: str = (
        "render materials (skin, fabric, surfaces) believably for the chosen style"
    )
    time_of_day_default: str = (
        "match the time of day implied by the script and the location reference"
    )


@dataclass
class CharacterHandling:
    """How subjects are treated in storyboards."""
    mode: str = "named_persistent"  # "archetype", "named_persistent", "no_characters"
    description: str = (
        "Use the characters that appear in the script, kept visually consistent "
        "with the attached cast sheet. Give them expressive faces and body "
        "language that convey each narrative beat. Do NOT invent characters who "
        "are not in the scene, and do NOT use real-world public figures by name."
    )
    reference_images: dict[str, str] = field(default_factory=dict)


@dataclass
class EmotionalArc:
    """Default 4-beat structure for scene-level storytelling."""
    beat_1: str = "Setup — establish the stakes, ground the viewer in the environment"
    beat_2: str = "Build — tension escalates, new information or threat emerges"
    beat_3: str = "Turn — the revelation, the shift, the moment everything changes"
    beat_4: str = "Payoff — consequence lands, emotional resolution or cliffhanger"


@dataclass
class ShotRequirements:
    """Hard rules for every storyboard grid."""
    mandatory_shots: list[str] = field(default_factory=lambda: [
        "1 environment-establishing wide (ELS or LS)",
        "1 intimate character close-up (CU or MCU)",
        "1 extreme detail shot (ECU) — hands, documents, screens, objects",
        "1 dynamic-angle shot (low angle or high angle)",
    ])
    continuity_rules: list[str] = field(default_factory=lambda: [
        "Strict continuity: same subjects, wardrobe, environment, lighting "
        "across all panels",
        "Only action, expression, blocking, framing, and camera movement "
        "may change between panels",
        "Depth of field must be realistic: deeper in wides, shallower in "
        "close-ups",
        "Maintain ONE consistent color grade across all 9 panels",
        "Do NOT introduce new characters/objects not established in the "
        "scene context",
    ])
    edit_rules: list[str] = field(default_factory=lambda: [
        "Ensure edit-motivated continuity between shots",
        "Eyeline match between sequential panels",
        "Action continuation across cuts",
        "Consistent screen direction / 180-degree axis",
    ])


@dataclass
class ChannelProfile:
    """Complete cinematic identity for the storyboard directive generator."""
    channel_name: str
    visual_style_directive: str
    lens_profile: LensProfile
    color_grade: ColorGrade
    character_handling: CharacterHandling
    emotional_arc: EmotionalArc
    shot_requirements: ShotRequirements
    duration_defaults: dict[str, float] = field(default_factory=dict)


# =============================================================================
# Model Profile — Video Generation Model Capabilities
# =============================================================================

@dataclass
class ModelProfile:
    """Defines a video generation model's capabilities and cost structure.

    Used by the duration-aware binner and video generation bot.
    Hot-swappable: changing the model on an Idea Concepts record
    re-runs duration binning with the new model's profile.
    """
    model_id: str
    display_name: str
    provider: str

    # Duration options (seconds, ascending)
    durations: list[int] = field(default_factory=lambda: [10])
    preferred_max: int = 10
    allow_max_override: bool = True

    # Cost per duration tier: {seconds: usd}
    cost_per_clip: dict[int, float] = field(default_factory=dict)

    # Capabilities
    resolution: str = "720p"
    supports_image_input: bool = True
    supports_first_last_frame: bool = False
    supports_camera_control: bool = False
    camera_control_type: str = "prompt"  # "prompt", "bracket", "keyframe", "none"
    aspect_ratios: list[str] = field(default_factory=lambda: ["16:9"])
    max_concurrent: int = 5
    avg_generation_time_seconds: int = 30

    # Audio
    includes_audio: bool = False
    strip_audio: bool = True

    # Single source of truth for "does this model have a live generation path".
    # Read directly by pipeline_executor.run_clip_generation's gate AND by
    # GET /api/models (storyengine/backend/routes/model_registry.py) — the
    # frontend's clip-model dropdown derives its selectable list from that
    # endpoint instead of hand-copying model ids, so this flag is the ONLY
    # place "wired" is decided (see tasks/storyengine-wiring-fix-checklist.md §0.2).
    wired: bool = False


# --- Model Instances ---

GROK_IMAGINE = ModelProfile(
    model_id="grok-imagine",
    display_name="Grok Imagine",
    provider="kie.ai",
    durations=[6, 10, 15],
    preferred_max=10,
    allow_max_override=True,
    # C09a (researched, kie.ai/grok-imagine, $0.005/credit): $0.008/s at 480p,
    # $0.015/s at 720p. StoryEngine requests 720p by default —
    # pipeline_executor.run_clip_generation: `_vres = video.get("video_resolution")
    # or "720p"` — so priced at the 720p rate. Duration is VARIABLE per clip
    # (clip_dialogue.pick_clip_duration rounds a spoken line up to the
    # smallest tier that fits, floor=6s for silent/short shots); each of the
    # 3 tiers below is 720p-rate x that tier's seconds (6*0.015, 10*0.015,
    # 15*0.015) so a caller picking any tier still prices accurately, not
    # just the cheapest one. A per-video 480p choice would over-charge here —
    # flagged as a known limitation (a fully resolution-aware ledger is a
    # bigger change than this pass).
    cost_per_clip={6: 0.09, 10: 0.15, 15: 0.225},
    resolution="720p",
    supports_image_input=True,
    supports_camera_control=False,
    camera_control_type="prompt",
    includes_audio=True,
    strip_audio=True,
    avg_generation_time_seconds=15,
    max_concurrent=10,
    wired=True,
)

VEO_31_FAST = ModelProfile(
    model_id="veo-3.1-fast",
    display_name="Veo 3.1 Fast",
    provider="kie.ai",
    durations=[8],
    preferred_max=8,
    allow_max_override=False,
    # C09a FLAGGED unconfirmed — dashboard check needed. Kie's public page
    # shows $0.40/8s, but a later Kie post claims a cut to $0.30/8s; unclear
    # whether that cut applies to 3.0 or 3.1, or both. This registry value
    # already matches the LOWER (cut) figure — left UNCHANGED rather than
    # bumped to the page's $0.40, since it's not clear which is current. See
    # tasks/live-verification-queue.md §C09.
    cost_per_clip={8: 0.30},
    resolution="720p",
    supports_image_input=True,
    supports_first_last_frame=True,
    supports_camera_control=False,
    camera_control_type="none",
    avg_generation_time_seconds=60,
    max_concurrent=5,
    wired=True,
)

VEO_31_QUALITY = ModelProfile(
    model_id="veo-3.1-quality",
    display_name="Veo 3.1 Quality",
    provider="kie.ai",
    durations=[8],
    preferred_max=8,
    allow_max_override=False,
    # C09a FLAGGED unconfirmed — same ambiguity as VEO_31_FAST above: page
    # says $2.00/8s, a later post claims a cut to $1.25/8s. This value
    # already matches the cut figure — left UNCHANGED, needs a dashboard
    # read to confirm. See tasks/live-verification-queue.md §C09.
    cost_per_clip={8: 1.25},
    resolution="1080p",
    supports_image_input=True,
    supports_first_last_frame=True,
    supports_camera_control=False,
    camera_control_type="none",
    avg_generation_time_seconds=120,
    max_concurrent=3,
    wired=True,
)

KLING_30_PRO = ModelProfile(
    model_id="kling-3.0-pro",
    display_name="Kling 3.0 Pro",
    provider="kie.ai",
    durations=[5, 10],
    preferred_max=10,
    allow_max_override=False,
    # C09a FLAGGED — only a "Turbo" tier's price was found on Kie's public
    # pages, not this exact "Pro" tier; unclear if they're the same SKU.
    # UNWIRED (no live generation path — see `wired=False` below), so left
    # unchanged rather than guessed. See tasks/live-verification-queue.md §C09.
    cost_per_clip={5: 0.80, 10: 1.50},
    resolution="1080p",
    supports_image_input=True,
    supports_camera_control=True,
    camera_control_type="keyframe",
    avg_generation_time_seconds=90,
    max_concurrent=3,
    wired=False,  # no live generation path yet
)

RUNWAY_GEN4_TURBO = ModelProfile(
    model_id="runway-gen4-turbo",
    display_name="Runway Gen-4 Turbo",
    provider="runway",
    durations=[5, 10],
    preferred_max=10,
    allow_max_override=False,
    # C09a FLAGGED — only found via a low-confidence secondary source (not
    # Runway's or Kie's own pricing page directly). UNWIRED (no live
    # generation path — see `wired=False` below), so left unchanged rather
    # than guessed. See tasks/live-verification-queue.md §C09.
    cost_per_clip={5: 0.25, 10: 0.50},
    resolution="720p",
    supports_image_input=True,
    supports_camera_control=True,
    camera_control_type="prompt",
    avg_generation_time_seconds=360,
    max_concurrent=5,
    wired=False,  # no live generation path yet
)

HAILUO_23_STANDARD = ModelProfile(
    model_id="hailuo-2.3-standard",
    display_name="Hailuo 2.3 Standard",
    provider="fal.ai",
    durations=[6, 10],
    preferred_max=10,
    allow_max_override=False,
    # C09a FLAGGED — fal.ai, not Kie, so out of scope for the $0.005/credit
    # Kie research pass. UNWIRED (no live generation path — see `wired=False`
    # below), left unchanged.
    cost_per_clip={6: 0.28, 10: 0.47},
    resolution="768p",
    supports_image_input=True,
    supports_camera_control=True,
    camera_control_type="bracket",
    avg_generation_time_seconds=45,
    max_concurrent=5,
    wired=False,  # no live generation path yet
)

SEEDANCE_2_FAST = ModelProfile(
    model_id="seedance-2-fast",
    display_name="Seedance 2.0 (Cinematic)",
    provider="kie.ai",
    durations=[6, 10],
    preferred_max=10,
    allow_max_override=False,
    # C09a (researched, kie.ai/seedance-2, $0.005/credit): 4 tiers exist —
    # 480p no-input $0.0775/s, 480p w/input $0.045/s, 720p no-input $0.165/s,
    # 720p w/input $0.100/s. `ImageClient.generate_video_seedance` (shared/
    # clients/image_client.py) HARDCODES `"resolution": "720p"` and ALWAYS
    # passes `first_frame_url` (an image input) — never variable, never
    # text-only — so the 720p-with-input tier ($0.100/s) is the one and only
    # tier this call site can ever hit. 6s = 6*0.100 = $0.60, 10s =
    # 10*0.100 = $1.00 (was 0.30/0.50 — the old numbers matched neither this
    # nor any other Kie seedance-2 tier; corrected).
    cost_per_clip={6: 0.60, 10: 1.00},
    resolution="720p",
    supports_image_input=True,
    supports_first_last_frame=True,
    supports_camera_control=True,
    camera_control_type="prompt",
    avg_generation_time_seconds=90,
    max_concurrent=3,
    wired=True,
)

# --- Model Registry ---

MODEL_REGISTRY: dict[str, ModelProfile] = {
    "grok-imagine": GROK_IMAGINE,
    "seedance-2-fast": SEEDANCE_2_FAST,
    "veo-3.1-fast": VEO_31_FAST,
    "veo-3.1-quality": VEO_31_QUALITY,
    "kling-3.0-pro": KLING_30_PRO,
    "runway-gen4-turbo": RUNWAY_GEN4_TURBO,
    "hailuo-2.3-standard": HAILUO_23_STANDARD,
}


# =============================================================================
# Generation prices — single source (storyengine-wiring-fix-checklist §0.3c
# / C09). Clip prices live on ModelProfile.cost_per_clip above; every OTHER
# paid stage's price is defined ONCE here. storyengine/backend/actions.py
# re-exports these under its pre-existing names (CLIP_COST, PICTURE_COST,
# THUMBNAIL_COST, VOICE_COST_ESTIMATE, SOUND_COST_ESTIMATE) so existing
# callers across pipeline_executor.py / coverage_to_app.py / chat.py don't
# need touching — but the NUMBERS live here, not in actions.py, and nowhere
# else (the frontend's hand-copied CLIP_COST_PER_MODEL literal was deleted
# in C09; the page now reads prices off the backend).
#
# Kie.ai's job-status response (recordInfo / veo/record-info) never carries
# a cost or credits-charged field for a completed task — confirmed by
# reading every field the two clients that poll it ever touch
# (shared/clients/image_client.py, storyengine/backend/kie_unified.py):
# only taskId/state/successFlag/resultUrls/failMsg/failCode ever appear, no
# matter which model ran. Kie does expose GET /api/v1/chat/credit (an
# account-wide REMAINING BALANCE, not a per-task charge), but with several
# clips/images generating concurrently (see ModelProfile.max_concurrent
# above) a balance snapshot can't be attributed to one generation without a
# race. There is no cleaner "actual" than these registry prices today — see
# tasks/live-verification-queue.md §C09 for the manual dashboard-reconciliation
# this leaves as a follow-up, and the report for which numbers below are
# still unconfirmed guesses vs. numbers backed by a real source.
#
# C09a (2026-07-18): prices below were updated from Kie's PUBLISHED per-model
# pricing pages at the confirmed $0.005/credit rate (kie.ai/<model>). This is
# real published pricing, not a per-task dashboard read — still not the exact
# "actual Kie charged this task X" number the paragraph above describes, but
# a large accuracy upgrade over the prior guesses (some of which mixed up a
# different model's price entirely — see git history). Each image model is
# tiered by RESOLUTION; the tier applied below is the one StoryEngine's live
# code path actually requests (quoted where each model is priced).
# =============================================================================

# Per-model image price ($/image), tiered by resolution — priced at the tier
# StoryEngine's live code actually requests, confirmed by reading the call
# sites (not assumed):
#   - gpt-image-2 (kie.ai/gpt-image-2): 1K=$0.03 (6 credits), 2K=$0.05
#     (10 credits), 4K=$0.08 (16 credits). GPT Image 2 is the default engine
#     (storyengine/CLAUDE.md "Image gen policy") and its live call path —
#     shared/clients/image_model_router.py's `generate_scene_image_for_model`
#     (the ONE resolver both coverage_to_app.py and pipeline_executor.py's
#     image-generating call sites use) — has `resolution: str = "2K"` as its
#     OWN default and every caller in this codebase (redo_characters,
#     storyboard sheets, redraw_asset_image, run_image_variants) calls it
#     WITHOUT overriding that default. That default flows straight into
#     ImageClient.generate_thumbnail_gpt2/generate_scene_image_gpt, which
#     also default resolution to "2K". So the tier actually requested is 2K
#     = $0.05, not the previous $0.08 (which was an unsourced guess at the
#     4K tier).
#   - nano-banana-2 (kie.ai/nano-banana-2): 1K=$0.04 (8 credits), 2K=$0.06
#     (12 credits), 4K=$0.09 (18 credits). This model is reached only via an
#     EXPLICIT image_model_override — image_model_router.py's nano-banana-2
#     branch calls ImageClient.generate_with_reference (default
#     resolution="1K") when references exist, or generate_scene_image
#     (hardcodes "resolution": "1K") otherwise — both request the 1K tier,
#     so priced at $0.04 (was $0.025, which was actually a stale "Seed Dream
#     4.5" figure per docs/cost-awareness.md — a different, no-longer-used
#     model name; corrected here).
#   - z-image (kie.ai/z-image): flat $0.004 (0.8 credits, no resolution
#     tiers) — matches the pre-existing value exactly, now confirmed against
#     published pricing rather than just the model-picker's own label text.
IMAGE_PRICE_BY_MODEL: dict[str, float] = {
    "gpt-image-2": 0.05,      # 2K tier — see comment above for the code trace
    "nano-banana-2": 0.04,    # 1K tier — see comment above for the code trace
    "z-image": 0.004,         # flat rate, confirmed against kie.ai/z-image
}
# Default/blended picture price — used pre-generation (no model chosen yet;
# GPT Image 2 is the default engine) and whenever a batch mixes models.
PICTURE_PRICE_DEFAULT = IMAGE_PRICE_BY_MODEL["gpt-image-2"]


def picture_price_for(model_id: Optional[str]) -> float:
    """Real per-model image price when the model is known and unambiguous
    (e.g. 'nano-banana-2'), else the default/blended price. A caller passing
    a comma-joined multi-model label (a mixed batch) falls through to the
    default on purpose — safer than guessing which model dominated."""
    if model_id and model_id in IMAGE_PRICE_BY_MODEL:
        return IMAGE_PRICE_BY_MODEL[model_id]
    return PICTURE_PRICE_DEFAULT


# C09a (2026-07-18): re-traced which model StoryEngine's thumbnail path
# ACTUALLY uses — the prior "Nano Banana Pro flat rate" label was wrong.
# `PipelineExecutor.run_thumbnail` (all 3 completion branches) and
# `_run_channel_formula_thumbnail` (storyengine/backend/pipeline_executor.py)
# call `ImageClient.generate_thumbnail_gpt2` / `generate_scene_image_gpt`
# — both GPT Image 2 — as the PRIMARY path every time; `generate_with_reference`
# (nano-banana-pro, kie.ai/nano-banana-pro: 1K/2K=$0.09, 4K=$0.12) only fires
# as a same-call FALLBACK when GPT returns no url (see run_thumbnail's
# cast-sheet branch). None of these calls pass an explicit `resolution`
# override, so — same as scene images above — they land on
# generate_thumbnail_gpt2/generate_scene_image_gpt's own "2K" default.
# Thumbnail price is therefore the SAME gpt-image-2 2K rate as scene images,
# not a separate Nano Banana Pro number. A model-aware
# `thumbnail_price_for(model_used)` (mirroring `picture_price_for`) would be
# more accurate for the rarer nano-banana-pro-fallback case, but the
# thumbnail ledger write doesn't currently thread `model_used` through to
# price by it — flagged as a follow-up, not built here (scope).
THUMBNAIL_PRICE = IMAGE_PRICE_BY_MODEL["gpt-image-2"]

# ElevenLabs is billed per character, not per run (docs/cost-awareness.md:
# ~$0.30/1000 chars) — a video with a long narration and one with a single
# line cost very differently even though both used to ledger the same flat
# $0.30. VOICE_PRICE_FLAT_ESTIMATE stays as the fallback for a caller that
# genuinely has no character count to meter (or the pre-generation "voice"
# verb quote, before scripts necessarily exist).
VOICE_PRICE_PER_1K_CHARS = 0.30
VOICE_PRICE_FLAT_ESTIMATE = 0.30

# Matches shared.clients.sound_client.SoundClient.ESTIMATED_COST_PER_GENERATION
# (the real per-generation figure the sound bot already tracks and the
# ledger's sound-stage write already reuses). Not re-sourced from here — kept
# as a same-value constant only so actions.py's pre-generation "sound" verb
# quote has a number without importing SoundClient's heavier module for an
# estimate.
SOUND_PRICE_ESTIMATE = 0.05


def clip_price_for(model_id: Optional[str]) -> float:
    """Cheapest wired price for a clip model, read straight off
    ModelProfile.cost_per_clip — the single source CLIP_PRICE_BY_MODEL below
    is built from."""
    profile = MODEL_REGISTRY.get(model_id or DEFAULT_VIDEO_MODEL)
    if not profile or not profile.cost_per_clip:
        return 0.10
    return profile.cost_per_clip[min(profile.cost_per_clip)]


# Every wired model's cheapest-tier price, keyed by model_id. This dict IS
# the single source actions.CLIP_COST re-exports and the frontend's (now-
# deleted) hand-copied CLIP_COST_PER_MODEL used to shadow by hand.
CLIP_PRICE_BY_MODEL: dict[str, float] = {
    model_id: clip_price_for(model_id)
    for model_id, profile in MODEL_REGISTRY.items()
    if profile.wired
}

DEFAULT_VIDEO_MODEL = "grok-imagine"


def load_model_profile(idea_record: Optional[dict] = None) -> ModelProfile:
    """Load video generation model profile.

    Reads 'Video Model' from idea record, falls back to DEFAULT_VIDEO_MODEL.
    """
    model_id = DEFAULT_VIDEO_MODEL
    if idea_record:
        override = idea_record.get("Video Model")
        if override and override in MODEL_REGISTRY:
            model_id = override
    return MODEL_REGISTRY[model_id]


# =============================================================================
# Default Profile — style-agnostic. The channel's actual look is supplied per
# video (image_style_override / Visual Style / the VISUAL_STYLE_DESCRIPTION the
# backend exports). This default must NOT impose any specific channel identity.
# =============================================================================

DEFAULT_PROFILE = ChannelProfile(
    channel_name="Default",

    visual_style_directive=(
        "Render in the channel's defined visual style, supplied per video and "
        "shown in the attached cast and location references — match those "
        "references exactly and never switch art styles mid-video. When no "
        "style is supplied, default to a clean, modern, cinematic look: "
        "characters with expressive faces performing actions in believable "
        "environments, with motivated lighting and clear compositions."
    ),

    lens_profile=LensProfile(),
    color_grade=ColorGrade(),
    character_handling=CharacterHandling(),
    emotional_arc=EmotionalArc(),
    shot_requirements=ShotRequirements(),

    duration_defaults={
        "ELS": 2.5,
        "LS": 2.0,
        "MLS": 1.5,
        "MS": 1.5,
        "MCU": 1.5,
        "CU": 1.5,
        "ECU": 1.0,
        "Low Angle": 1.5,
        "High Angle": 1.5,
        "Worm's-eye": 1.0,
        "Bird's-eye": 1.5,
        "Insert": 1.0,
    },
)


def _build_visual_style_directive(profile_id: str) -> Optional[str]:
    """Resolve a storyboard-ready style directive from a visual profile id."""
    visual_profile = load_visual_profile(profile_id)
    if visual_profile is None:
        return None

    parts: list[str] = []
    if visual_profile.profile_name:
        parts.append(visual_profile.profile_name)
    if visual_profile.description:
        parts.append(visual_profile.description)

    style_system = getattr(visual_profile, "style_system", None)
    if style_system is not None:
        if getattr(style_system, "style_prefix", ""):
            parts.append(style_system.style_prefix.strip())
        if getattr(style_system, "style_suffix", ""):
            parts.append(style_system.style_suffix.strip().lstrip(','))

    figure_rules = getattr(visual_profile, "figure_rules", None)
    if figure_rules is not None and getattr(figure_rules, "negative_prompt_suffix", ""):
        parts.append(f"Figure rules: {figure_rules.negative_prompt_suffix.strip()}")

    return " ".join(part for part in parts if part).strip() or None


def load_profile(idea_record: Optional[dict] = None) -> ChannelProfile:
    """Load the channel profile for storyboard generation.

    The base profile is style-agnostic (DEFAULT_PROFILE). The channel's actual
    look is layered on in priority order:
      1. idea_record['Image Style Override'] — freeform per-video instruction.
      2. idea_record['Visual Style'] — a preset style id, resolved to a directive.
      3. VISUAL_STYLE_DESCRIPTION env var — the look the backend exports for this
         video (the engine seam), so the directive uses it even when the idea
         record didn't carry the field. This closes the gap where the storyboard
         directive ignored the backend's resolved look.
      4. otherwise the neutral default.
    """
    profile = ChannelProfile(
        channel_name=DEFAULT_PROFILE.channel_name,
        visual_style_directive=DEFAULT_PROFILE.visual_style_directive,
        lens_profile=DEFAULT_PROFILE.lens_profile,
        color_grade=DEFAULT_PROFILE.color_grade,
        character_handling=DEFAULT_PROFILE.character_handling,
        emotional_arc=DEFAULT_PROFILE.emotional_arc,
        shot_requirements=DEFAULT_PROFILE.shot_requirements,
        duration_defaults=dict(DEFAULT_PROFILE.duration_defaults),
    )

    if idea_record:
        # Freeform per-video instructions win over any preset style id.
        image_style_override = idea_record.get("Image Style Override")
        if image_style_override and isinstance(image_style_override, str) and image_style_override.strip():
            profile.visual_style_directive = image_style_override.strip()
            return profile

        visual_style = idea_record.get("Visual Style")
        if visual_style and isinstance(visual_style, str) and visual_style.strip():
            resolved_directive = _build_visual_style_directive(visual_style.strip())
            profile.visual_style_directive = resolved_directive or visual_style.strip()
            return profile

    # Engine seam: the backend exports the resolved channel look here so the
    # directive matches the rest of the pipeline even without an idea_record field.
    env_style = os.getenv("VISUAL_STYLE_DESCRIPTION")
    if env_style and env_style.strip():
        profile.visual_style_directive = env_style.strip()

    return profile
