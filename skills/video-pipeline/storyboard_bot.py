"""
Storyboard Bot — Cinematic shot planning and contact sheet generation.

Generates 3x3 cinematic contact sheet storyboards for each narrative beat
BEFORE individual image generation. A Claude-powered directive generator
acts as a trailer director — analyzing script text, planning emotional arcs,
choosing shot types/angles/durations, and outputting keyframe specifications.

This is an OPTIONAL pre-step. When disabled, the pipeline flows as normal.
Manual trigger only via Slack commands (!storyboard-go, !storyboard-beat).

Pipeline flow (with storyboard enabled):
  Ready For Image Prompts → image_prompt_bot generates prompts (unchanged)
      ↓
  Ready For Storyboards → storyboard_bot (NEW — manual trigger)
      ↓
  Ready For Video Scripts (skips image_bot — images already generated)
"""

from __future__ import annotations

import logging
import math
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from channel_profile import ChannelProfile, load_profile
from pipeline_constants import ImageFields, Models, ScriptFields

logger = logging.getLogger(__name__)


# =============================================================================
# Grid Count Calculator
# =============================================================================

def calculate_grid_count(
    video_length_minutes: int,
    clip_duration_seconds: int = 10,
) -> dict:
    """Calculate how many storyboard grids are needed for a video.

    Returns dict with grid_count, total_panels, and cost estimate.
    """
    total_seconds = video_length_minutes * 60
    total_clips = total_seconds // clip_duration_seconds

    grid_count = math.ceil(total_clips / 9)
    total_panels = grid_count * 9

    cost_claude = grid_count * 0.03
    cost_grids = grid_count * 0.075
    cost_upscale = total_panels * 0.045
    total_cost = cost_claude + cost_grids + cost_upscale

    return {
        "grid_count": grid_count,
        "total_panels": total_panels,
        "surplus_panels": total_panels - total_clips,
        "cost_claude": cost_claude,
        "cost_grids": cost_grids,
        "cost_upscale": cost_upscale,
        "total_cost": total_cost,
    }


# =============================================================================
# Narrative Beat Segmentation
# =============================================================================

def segment_script_into_beats(
    script_records: list[dict],
    target_seconds_per_beat: int = 40,
    words_per_second: float = 2.5,
) -> list[dict]:
    """Divide the full script into narrative beats for storyboard generation.

    Each beat targets ~40 seconds of narration (~100 words at 2.5 wps).
    Respects scene boundaries — never splits mid-scene.

    Args:
        script_records: Airtable script records with 'Scene', 'Scene text' fields.
        target_seconds_per_beat: Target duration per beat in seconds.
        words_per_second: Narration speed (2.5 wps standard).

    Returns:
        List of beats, each with beat_number, scenes, text, word_count,
        estimated_duration_seconds.
    """
    target_words_per_beat = int(target_seconds_per_beat * words_per_second)

    beats: list[dict] = []
    current_beat_text = ""
    current_beat_scenes: list[int] = []
    current_word_count = 0
    beat_number = 1

    sorted_records = sorted(
        script_records,
        key=lambda r: r.get(ScriptFields.SCENE, r.get("fields", {}).get(ScriptFields.SCENE, 0)),
    )

    for record in sorted_records:
        # Handle both flat {"Scene": N} and nested {"fields": {"Scene": N}}
        fields = record.get("fields", record)
        scene_num = fields.get(ScriptFields.SCENE, 0)
        scene_text = fields.get(ScriptFields.SCENE_TEXT, "")
        scene_words = len(scene_text.split())

        # If adding this scene exceeds 130% of target AND we already have content,
        # close the current beat and start a new one
        if (
            current_word_count + scene_words > target_words_per_beat * 1.3
            and current_word_count > 0
        ):
            beats.append({
                "beat_number": beat_number,
                "scenes": list(current_beat_scenes),
                "text": current_beat_text.strip(),
                "word_count": current_word_count,
                "estimated_duration_seconds": current_word_count / words_per_second,
            })
            beat_number += 1
            current_beat_text = ""
            current_beat_scenes = []
            current_word_count = 0

        current_beat_text += f"\n{scene_text}"
        current_beat_scenes.append(scene_num)
        current_word_count += scene_words

    # Don't forget the last beat
    if current_word_count > 0:
        beats.append({
            "beat_number": beat_number,
            "scenes": list(current_beat_scenes),
            "text": current_beat_text.strip(),
            "word_count": current_word_count,
            "estimated_duration_seconds": current_word_count / words_per_second,
        })

    return beats


# =============================================================================
# Cinematic Directive Generator — Core Intelligence
# =============================================================================

def _build_directive_system_prompt(profile: ChannelProfile) -> str:
    """Build the system prompt for the cinematic directive generator."""
    return f"""\
<role>
You are an award-winning trailer director, cinematographer, and storyboard artist working \
on a cinematic documentary-style video. Your job: turn script narration into a cohesive \
cinematic shot sequence, then output AI-video-ready keyframes as a 3×3 contact sheet.
</role>

<channel_identity>
Channel: {profile.channel_name}
Visual Style: {profile.visual_style_directive}
</channel_identity>

<lens_and_camera>
Focal Range: {profile.lens_profile.focal_range}
Depth of Field Tendency: {profile.lens_profile.dof_tendency}
Movement Vocabulary: {', '.join(profile.lens_profile.movement_vocabulary)}
Shutter Feel: {profile.lens_profile.shutter_feel}
Grain/Texture: {profile.lens_profile.grain}
</lens_and_camera>

<color_grade>
Primary Palette: {profile.color_grade.primary_palette}
Contrast: {profile.color_grade.contrast}
Shadow Treatment: {profile.color_grade.shadow_treatment}
Highlight Treatment: {profile.color_grade.highlight_treatment}
Material Priorities: {profile.color_grade.material_priorities}
Time of Day: {profile.color_grade.time_of_day_default}
</color_grade>

<character_handling>
Mode: {profile.character_handling.mode}
{profile.character_handling.description}
</character_handling>

<non_negotiable_rules>
1) Analyze the scene narration to identify ALL key subjects, environments, and narrative beats. \
Describe spatial relationships and interactions.
2) Do NOT use real political figure names. Imply through context (setting, wardrobe, insignia).
3) Strict continuity across ALL 9 panels: same subjects, same wardrobe/appearance, same \
environment, same time-of-day and lighting. Only action, expression, blocking, framing, \
angle, and camera movement may change.
4) Depth of field must be realistic per the lens profile. Keep ONE consistent cinematic color \
grade across the entire sequence per the color grade profile.
5) Do NOT introduce new characters/objects not supported by the narration. If you need \
tension/conflict beyond what's described, imply it off-screen (shadow, reflection, gaze).
</non_negotiable_rules>

<goal>
Expand the scene narration into a 9-keyframe cinematic sequence with a clear emotional \
progression following the 4-beat arc: {profile.emotional_arc.beat_1} → \
{profile.emotional_arc.beat_2} → {profile.emotional_arc.beat_3} → \
{profile.emotional_arc.beat_4}.

Total suggested duration for all 9 keyframes: 10-20 seconds (this will be one beat \
in a larger video).
</goal>

<output_format>
You MUST output ALL of the following sections in order:

## SCENE BREAKDOWN
- Subjects: list each key subject (A/B/C...), describe visible traits, relative positions, \
facing direction, action/state, and any interaction.
- Environment & Lighting: interior/exterior, spatial layout, background elements, light \
direction & quality, implied time-of-day, 3-8 vibe keywords.
- Visual Anchors: list 3-6 visual traits that MUST stay constant across all 9 panels \
(palette, signature prop, key light source, weather/atmosphere, background markers).

## THEME & STORY
- Theme: one sentence.
- Logline: one restrained sentence grounded in the narration.
- Emotional Arc: 4 beats (setup/build/turn/payoff), one line each.

## CINEMATIC APPROACH
- Shot progression strategy: how you move from wide to close (or reverse) to serve the beats.
- Camera movement plan: which movements from the channel's vocabulary and WHY.
- Lens & exposure: focal lengths, DoF shifts, shutter feel.
- Light & color: how the channel's color grade applies to THIS scene specifically.

## KEYFRAMES
Output exactly 9 keyframes. Use this EXACT format per keyframe:

[KF# | shot_type | duration_seconds]
- Composition: subject placement, foreground/mid/background, leading lines, gaze direction
- Action/beat: what visibly happens (simple, executable by an image model)
- Camera: height, angle, movement description
- Lens/DoF: focal length (mm), DoF (shallow/medium/deep), focus target
- Lighting & grade: consistent with color grade profile; note highlight/shadow emphasis
- Sound/atmos: one line (wind, city hum, footsteps, paper rustling) — for editing rhythm reference

Hard requirements for the 9 keyframes:
{chr(10).join('- ' + req for req in profile.shot_requirements.mandatory_shots)}

Edit continuity rules:
{chr(10).join('- ' + rule for rule in profile.shot_requirements.edit_rules)}

## CONTACT SHEET PROMPT
Finally, output a SINGLE image generation prompt that will produce a 3×3 contact sheet \
grid containing all 9 keyframes as panels. This prompt will be sent directly to an image \
generation model.

The contact sheet prompt MUST:
- Begin with the channel's visual style directive
- Describe a 3×3 grid layout (3 rows, 3 columns) with clearly separated panels
- Include panel labels: [KF# | shot_type | duration] in the top-left corner of each panel
- Describe each panel's content in sequence (KF1 top-left → KF9 bottom-right)
- Enforce consistent character appearance, environment, and color grade across all panels
- End with technical specs: the channel's lens profile, grain/texture, and color grade
</output_format>"""


def _build_directive_user_prompt(
    beat_number: int,
    beat_text: str,
    beat_scenes: list[int],
    video_title: str,
    image_prompts: list[str],
) -> str:
    """Build the user message for the directive generator."""
    formatted_prompts = "\n".join(
        f"  [{i + 1}] {p}" for i, p in enumerate(image_prompts) if p
    ) or "  (no existing image prompts)"

    return f"""\
Generate the cinematic storyboard directive for Beat {beat_number} \
of "{video_title}".

Scenes covered: {', '.join(str(s) for s in beat_scenes)}

Beat narration:
{beat_text}

Reference image prompts (use as context for subjects and environments):
{formatted_prompts}"""


async def generate_storyboard_directive(
    beat_number: int,
    beat_text: str,
    beat_scenes: list[int],
    video_title: str,
    image_prompts: list[str],
    profile: ChannelProfile,
    anthropic_client=None,
) -> dict:
    """Generate a cinematic directive for one narrative beat via Claude.

    Returns dict with:
        scene_breakdown, theme_and_story, cinematic_approach,
        keyframes (parsed list), contact_sheet_prompt, full_response.
    """
    if anthropic_client is None:
        from clients.anthropic_client import AnthropicClient
        anthropic_client = AnthropicClient()

    system_prompt = _build_directive_system_prompt(profile)
    user_prompt = _build_directive_user_prompt(
        beat_number, beat_text, beat_scenes, video_title, image_prompts,
    )

    response = await anthropic_client.generate(
        prompt=user_prompt,
        system_prompt=system_prompt,
        model=Models.CLAUDE_SONNET,
        max_tokens=6000,
        temperature=0.9,
    )

    # Parse sections from the response
    keyframes = parse_keyframe_metadata(response)
    contact_sheet_prompt = extract_contact_sheet_prompt(response)

    return {
        "beat_number": beat_number,
        "scene_breakdown": _extract_section(response, "SCENE BREAKDOWN"),
        "theme_and_story": _extract_section(response, "THEME & STORY"),
        "cinematic_approach": _extract_section(response, "CINEMATIC APPROACH"),
        "keyframes": keyframes,
        "contact_sheet_prompt": contact_sheet_prompt,
        "full_response": response,
    }


# =============================================================================
# Response Parsers
# =============================================================================

def parse_keyframe_metadata(directive_text: str) -> list[dict]:
    """Parse the KEYFRAMES section to extract per-panel metadata.

    Looks for patterns like: [KF1 | ELS | 2.0]
    Returns list of dicts with shot_type, duration_seconds, and sub-field text.
    """
    # Match pattern: [KF# | shot_type | duration]
    pattern = r"\[KF(\d+)\s*\|\s*([^|]+?)\s*\|\s*([\d.]+)\s*s?\s*\]"
    matches = list(re.finditer(pattern, directive_text))

    if not matches:
        logger.warning("No keyframe headers found in directive response")
        return []

    keyframes: list[dict] = []

    for i, match in enumerate(matches):
        kf_number = int(match.group(1))
        shot_type = match.group(2).strip()
        duration = float(match.group(3))

        # Extract description block between this header and the next
        start_pos = match.end()
        end_pos = matches[i + 1].start() if i < len(matches) - 1 else len(directive_text)
        description_block = directive_text[start_pos:end_pos].strip()

        # Stop at section boundaries (## headers)
        section_break = re.search(r"\n##\s", description_block)
        if section_break:
            description_block = description_block[: section_break.start()].strip()

        keyframes.append({
            "kf_number": kf_number,
            "shot_type": shot_type,
            "duration_seconds": duration,
            "composition": _extract_field(description_block, "Composition"),
            "action_beat": _extract_field(description_block, "Action/beat")
            or _extract_field(description_block, "Action"),
            "camera": _extract_field(description_block, "Camera"),
            "lens_dof": _extract_field(description_block, "Lens/DoF")
            or _extract_field(description_block, "Lens"),
            "lighting_grade": _extract_field(description_block, "Lighting & grade")
            or _extract_field(description_block, "Lighting"),
            "sound_atmos": _extract_field(description_block, "Sound/atmos")
            or _extract_field(description_block, "Sound"),
            "full_description": description_block,
        })

    return keyframes


def extract_contact_sheet_prompt(directive_text: str) -> str:
    """Extract the contact sheet image generation prompt from the directive.

    Looks for the ## CONTACT SHEET PROMPT section.
    """
    markers = [
        "## CONTACT SHEET PROMPT",
        "CONTACT SHEET PROMPT",
        "Contact Sheet Prompt",
        "MASTER GRID",
    ]

    idx = -1
    marker_len = 0
    for marker in markers:
        idx = directive_text.find(marker)
        if idx != -1:
            marker_len = len(marker)
            break

    if idx == -1:
        raise ValueError("Could not find CONTACT SHEET PROMPT section in directive")

    prompt_text = directive_text[idx + marker_len :].strip()

    # Remove any subsequent markdown sections
    next_section = re.search(r"\n##\s", prompt_text)
    if next_section:
        prompt_text = prompt_text[: next_section.start()].strip()

    return prompt_text


def _extract_section(text: str, section_name: str) -> str:
    """Extract a named ## section from the directive response."""
    pattern = rf"##\s*{re.escape(section_name)}\s*\n(.*?)(?=\n##\s|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_field(text: str, field_name: str) -> str:
    """Extract a field value from a keyframe description block."""
    pattern = rf"-\s*{re.escape(field_name)}[^:]*:\s*(.+?)(?=\n-|\n\n|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


# =============================================================================
# Beat Preview Formatter (for Slack / --directive-only)
# =============================================================================

def format_beat_preview(
    video_title: str,
    beat: dict,
    total_beats: int,
    keyframes: list[dict],
    directive: dict,
) -> str:
    """Format a single beat's directive into a readable summary.

    Used by --directive-only mode and !storyboard-preview Slack command.
    """
    lines = [
        f"🎬 Beat {beat['beat_number']}/{total_beats} — \"{video_title}\"",
        f"📍 Scenes {', '.join(str(s) for s in beat['scenes'])} | "
        f"~{beat['estimated_duration_seconds']:.0f}s | {beat['word_count']} words",
        "",
    ]

    # Theme & arc from directive
    theme_story = directive.get("theme_and_story", "")
    if theme_story:
        # Extract theme line
        theme_match = re.search(r"Theme:\s*(.+)", theme_story)
        if theme_match:
            lines.append(f"Theme: {theme_match.group(1).strip()}")

    # Shot plan
    lines.append("")
    lines.append("Shot Plan:")
    for kf in keyframes:
        action = kf.get("action_beat", "")
        # Truncate action to ~60 chars for readability
        if len(action) > 60:
            action = action[:57] + "..."
        lines.append(
            f"  KF{kf['kf_number']} | {kf['shot_type']:5s} | "
            f"{kf['duration_seconds']:.1f}s — {action}"
        )

    # Total duration
    total_dur = sum(kf.get("duration_seconds", 0) for kf in keyframes)
    lines.append(f"\n  Total: {total_dur:.1f}s across {len(keyframes)} keyframes")

    return "\n".join(lines)


# =============================================================================
# Storyboard Plan Generator (cost estimate, no execution)
# =============================================================================

async def generate_storyboard_plan(
    idea_record: dict,
    airtable_client=None,
) -> dict:
    """Generate a storyboard plan WITHOUT executing it.

    Called by !storyboard command to show cost estimate and beat breakdown.
    """
    if airtable_client is None:
        from clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()

    fields = idea_record.get("fields", idea_record)
    video_title = fields.get("Video Title", "")
    video_length = fields.get("Video Length (min)", 10)
    clip_duration = fields.get("Clip Duration (s)", 10)

    script_records = airtable_client.get_scripts_by_title(video_title)
    if not script_records:
        return {"error": f"No script found for '{video_title}'"}

    total_words = sum(
        len(r.get("fields", r).get(ScriptFields.SCENE_TEXT, "").split())
        for r in script_records
    )
    scene_count = len(script_records)

    beats = segment_script_into_beats(script_records)
    grid_count = len(beats)
    total_panels = grid_count * 9

    cost = calculate_grid_count(video_length, clip_duration)

    return {
        "video_title": video_title,
        "total_words": total_words,
        "scene_count": scene_count,
        "video_length_minutes": video_length,
        "clip_duration_seconds": clip_duration,
        "beat_count": grid_count,
        "total_panels": total_panels,
        "beats": beats,
        "cost_claude": cost["cost_claude"],
        "cost_grids": cost["cost_grids"],
        "cost_upscale": cost["cost_upscale"],
        "total_cost": cost["total_cost"],
    }


# =============================================================================
# Directive-Only Preview (Claude calls, no image generation)
# =============================================================================

async def run_storyboard_preview(
    idea_record: dict,
    airtable_client=None,
    anthropic_client=None,
    single_beat: Optional[int] = None,
) -> list[dict]:
    """Run directives only — no image generation.

    Returns list of beat results, each containing the directive and
    formatted preview. Used by !storyboard-preview and --directive-only.
    """
    if airtable_client is None:
        from clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()
    if anthropic_client is None:
        from clients.anthropic_client import AnthropicClient
        anthropic_client = AnthropicClient()

    fields = idea_record.get("fields", idea_record)
    video_title = fields.get("Video Title", "")
    profile = load_profile(fields)

    script_records = airtable_client.get_scripts_by_title(video_title)
    if not script_records:
        logger.error(f"No script found for '{video_title}'")
        return []

    beats = segment_script_into_beats(script_records)
    if single_beat is not None:
        beats = [b for b in beats if b["beat_number"] == single_beat]

    image_records = airtable_client.get_all_images_for_video(video_title)

    results: list[dict] = []

    for beat in beats:
        beat_images = _get_images_for_beat(image_records, beat)
        image_prompts = [
            img.get(ImageFields.IMAGE_PROMPT, "")
            for img in beat_images
        ]

        directive = await generate_storyboard_directive(
            beat_number=beat["beat_number"],
            beat_text=beat["text"],
            beat_scenes=beat["scenes"],
            video_title=video_title,
            image_prompts=image_prompts,
            profile=profile,
            anthropic_client=anthropic_client,
        )

        preview = format_beat_preview(
            video_title=video_title,
            beat=beat,
            total_beats=len(beats),
            keyframes=directive["keyframes"],
            directive=directive,
        )

        results.append({
            "beat": beat,
            "directive": directive,
            "preview": preview,
        })

        logger.info(f"Beat {beat['beat_number']}/{len(beats)} directive generated")

    return results


# =============================================================================
# Internal Helpers
# =============================================================================

def _get_images_for_beat(
    all_image_records: list[dict],
    beat: dict,
) -> list[dict]:
    """Filter image records to those belonging to scenes in this beat."""
    beat_scenes = set(beat["scenes"])
    return [
        img for img in all_image_records
        if img.get(ImageFields.SCENE, img.get("fields", {}).get(ImageFields.SCENE, 0))
        in beat_scenes
    ]
