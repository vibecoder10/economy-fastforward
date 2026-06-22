"""Coverage storyboard generator (Phase 1 of the Seedance pipeline plan).

Coverage = per narrative MOMENT, several matched camera angles of the SAME instant
(a wide master + tighter/alternate angles) that cut together like a multi-camera shoot.
This is the content-engine beats/coverage approach ported into StoryEngine.

The trick that makes angles match: generate the moment's MASTER frame anchored on the
cast sheet, then generate each ANGLE anchored on BOTH the cast sheet AND the master frame,
told "only the camera angle changes." Same call the 3x3 grid path already uses
(image_client.generate_with_reference) — so this touches neither image_client.py nor
pipeline_executor.py.

NEW mode, gated: nothing here is wired into the live pipeline. The existing 3x3 storyboard
flow (run_storyboard_images / generate_contact_sheet) is untouched. Reach this only via the
CLI below; pipeline wiring + route picker are Phase 4.

  coverage.py estimate <spec.json>
  coverage.py run <spec.json> <outdir>

spec.json (see proof_spec.json): cast_url OR cast_prompt, beat_text OR directive_text,
optional video_title / story_bible / max_moments / aspect.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # video-pipeline root (shared/, orchestrator/)
sys.path.insert(0, _HERE)

from storyboard.bot import (  # noqa: E402  reuse, don't reinvent
    _format_story_bible_for_beat,
    build_image_prompt_from_keyframe,
)
from shared.channel_profile import load_profile  # noqa: E402
from orchestrator.pipeline_constants import Models  # noqa: E402

SHOT_TYPES = "ELS, WS, MS, MCU, CU, ECU, OTS, INSERT"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


# =============================================================================
# Directive — per moment, a master + matched angles of the same instant
# =============================================================================

def _coverage_system_prompt(profile, max_moments: int, angles_min: int, angles_max: int) -> str:
    cg = profile.color_grade
    return f"""\
You are an award-winning cinematographer and storyboard artist planning COVERAGE for a \
cinematic video.

COVERAGE means: for each narrative MOMENT you plan several camera angles of the SAME instant — \
a wide MASTER that establishes the moment, then tighter or alternate ANGLES (medium, close-up, \
over-the-shoulder, insert) that cut together as if shot by a multi-camera crew. Angles within a \
moment show the EXACT same instant: same staging, wardrobe, props, lighting and time of day — \
only the camera moves.

<channel_style>
Visual style: {profile.visual_style_directive}
Color grade: {cg.primary_palette}; {cg.contrast}; {cg.time_of_day_default}
Lens: {profile.lens_profile.focal_range}
</channel_style>

<rules>
1) NO INVENTED PEOPLE — only characters named in the VISUAL BIBLE may appear. Never add a guest, \
extra, sibling, neighbour or crowd member, and never invent a name. If a moment names no one, \
show the existing cast or the empty environment.
2) The VISUAL BIBLE (if provided) is BINDING for character appearance and locations. Use the exact \
wardrobe, face and setting. It overrides any other description of how a character or place looks.
3) Within a moment every angle is the SAME instant — identical wardrobe, props, blocking, light. \
Only framing/angle/lens changes. Angles must be genuinely DISTINCT (different shot size AND a \
different visual focus: face vs hands vs object), never near-duplicate zooms of one framing.
4) Across moments keep continuity: same characters, consistent palette and light per location.
</rules>

<output_format>
Output ONLY the coverage plan, nothing else. For each moment:

[MOMENT n | one-line description of what happens]
- MASTER [shot_type]: full visual description — subjects with exact appearance, environment, \
blocking, lighting. This is the widest / establishing framing of the moment.
- ANGLE [shot_type]: same instant, different camera — the new framing and what it emphasises.
- ANGLE [shot_type]: ...

shot_type is one of: {SHOT_TYPES}.
Give each moment ONE MASTER plus {angles_min}-{angles_max} ANGLES.
Plan up to {max_moments} moments from the narration below; pick the moments that carry the scene.
</output_format>"""


def _coverage_user_prompt(beat_text, video_title, story_bible, beat_scenes, image_prompts) -> str:
    parts = [f'Plan cinematic COVERAGE for "{video_title or "this scene"}".',
             f"\nScene narration:\n{beat_text.strip()}"]
    bible = _format_story_bible_for_beat(story_bible, beat_scenes or [])
    if bible:
        parts.append(f"\n--- VISUAL BIBLE (binding) ---\n{bible}\n--- END VISUAL BIBLE ---")
    if image_prompts:
        listed = "\n".join(f"  - {p}" for p in image_prompts if p)
        parts.append(f"\n--- EXISTING SHOT IDEAS (use as the moments to cover) ---\n{listed}")
    return "\n".join(parts)


async def generate_coverage_directive(
    beat_text, video_title, profile, story_bible, beat_scenes, image_prompts,
    max_moments=3, angles_min=2, angles_max=4, anthropic_client=None,
) -> str:
    """Run Claude to produce the coverage plan text. Returns the raw directive."""
    if anthropic_client is None:
        from shared.clients.anthropic_client import AnthropicClient
        anthropic_client = AnthropicClient()
    return await anthropic_client.generate(
        prompt=_coverage_user_prompt(beat_text, video_title, story_bible, beat_scenes, image_prompts),
        system_prompt=_coverage_system_prompt(profile, max_moments, angles_min, angles_max),
        model=Models.CLAUDE_SONNET,
        max_tokens=6000,
        temperature=0.7,
    )


# =============================================================================
# Parser
# =============================================================================

_MOMENT_RE = re.compile(r"\[MOMENT\s+(\d+)\s*\|\s*([^\]]*)\]", re.IGNORECASE)
_SHOT_RE = re.compile(
    r"-\s*(MASTER|ANGLE)\s*\[([^\]]+)\]\s*:?\s*(.+?)(?=\n\s*-\s*(?:MASTER|ANGLE)\b|\n\s*\[MOMENT|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def parse_coverage(directive_text: str) -> list[dict]:
    """Parse the coverage plan into moments. Each moment: {moment_number, summary,
    master:{shot_type,description}, angles:[{shot_type,description}, ...]}."""
    heads = list(_MOMENT_RE.finditer(directive_text))
    moments: list[dict] = []
    for i, h in enumerate(heads):
        block = directive_text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(directive_text)]
        master, angles = None, []
        for m in _SHOT_RE.finditer(block):
            shot = {"shot_type": m.group(2).strip().upper(), "description": m.group(3).strip()}
            if m.group(1).upper() == "MASTER" and master is None:
                master = shot
            else:
                angles.append(shot)
        if master and angles:  # a moment needs a master + at least one angle to be coverage
            moments.append({"moment_number": int(h.group(1)), "summary": h.group(2).strip(),
                            "master": master, "angles": angles})
    return moments


# =============================================================================
# Image generation — the reference-chaining port
# =============================================================================

def _url_of(result):
    return result.get("url") if isinstance(result, dict) else result


async def generate_coverage_frames(moment, cast_url, image_client, profile,
                                   env_url=None, aspect="16:9", resolution="2K") -> list[dict] | None:
    """Master frame (anchored on cast) -> each angle (anchored on cast + master).
    Returns frames [{role, shot_type, description, url}] or None if the master fails."""
    base = [cast_url] + ([env_url] if env_url else [])
    m = moment["master"]
    master_prompt = build_image_prompt_from_keyframe({"composition": m["description"]}, profile)
    master_url = _url_of(await image_client.generate_with_reference(
        prompt=master_prompt, reference_image_url=base, aspect_ratio=aspect, resolution=resolution))
    if not master_url:
        return None
    frames = [{"role": "master", "shot_type": m["shot_type"], "description": m["description"], "url": master_url}]
    for a in moment["angles"]:
        ap = build_image_prompt_from_keyframe({"composition": a["description"]}, profile)
        ap += (" Match the lighting, wardrobe, staging and setting of the attached reference exactly; "
               "this is the SAME moment from a different camera — only the angle and framing change.")
        refs = [cast_url, master_url] + ([env_url] if env_url else [])
        url = _url_of(await image_client.generate_with_reference(
            prompt=ap, reference_image_url=refs, aspect_ratio=aspect, resolution=resolution))
        if url:
            frames.append({"role": "angle", "shot_type": a["shot_type"], "description": a["description"], "url": url})
    return frames


def _download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


async def run_coverage(beat_text, cast_url, image_client, *, outdir, video_title="",
                       profile=None, story_bible=None, beat_scenes=None, env_url=None,
                       image_prompts=None, directive_text=None, anthropic_client=None,
                       max_moments=3, aspect="16:9", resolution="2K") -> dict:
    """Build coverage for one scene/beat: directive -> parse -> matched frames per moment.
    Saves frames + coverage.json locally with angle/shot-type metadata. No DB writes
    (storing into Image records is Phase 2, where the animator consumes them)."""
    profile = profile or load_profile({})
    os.makedirs(outdir, exist_ok=True)
    if directive_text is None:
        directive_text = await generate_coverage_directive(
            beat_text, video_title, profile, story_bible, beat_scenes, image_prompts or [],
            max_moments=max_moments, anthropic_client=anthropic_client)
    with open(os.path.join(outdir, "directive.txt"), "w") as f:
        f.write(directive_text)

    moments = parse_coverage(directive_text)
    if not moments:
        return {"error": "no moments parsed from directive", "directive_chars": len(directive_text)}

    result_moments, frame_total = [], 0
    for moment in moments:
        frames = await generate_coverage_frames(
            moment, cast_url, image_client, profile, env_url=env_url, aspect=aspect, resolution=resolution)
        if not frames:
            print(f"  [moment {moment['moment_number']}] master failed — skipped", flush=True)
            continue
        for fr in frames:
            name = f"m{moment['moment_number']:02d}_{fr['role']}_{fr['shot_type'].lower()}.png"
            try:
                _download(fr["url"], os.path.join(outdir, name))
                fr["file"] = name
            except Exception as e:
                print(f"  download failed {name}: {e}", flush=True)
            frame_total += 1
        result_moments.append({**moment, "frames": frames})
        print(f"  [moment {moment['moment_number']}] {len(frames)} frames "
              f"({', '.join(fr['shot_type'] for fr in frames)})", flush=True)

    out = {"video_title": video_title, "moments": result_moments,
           "moment_count": len(result_moments), "frame_count": frame_total}
    with open(os.path.join(outdir, "coverage.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


# =============================================================================
# CLI
# =============================================================================

def _load_env():
    """Populate KIE/Anthropic keys from the repo .env so the clients find them."""
    for p in (os.path.expanduser("~/economy-fastforward/.env"),
              os.path.expanduser("~/economy-fastforward/storyengine/backend/.env")):
        try:
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(("KIE_AI_API_KEY=", "ANTHROPIC_API_KEY=")):
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k, v.strip().strip('"').strip("'"))
        except FileNotFoundError:
            continue


def _moments_estimate(spec) -> dict:
    mm = spec.get("max_moments", 3)
    per = 1 + 3  # master + ~3 angles
    frames = mm * per
    seed = 1 if spec.get("cast_prompt") and not spec.get("cast_url") else 0
    total = frames + seed
    return {"moments": mm, "frames_per_moment": per, "image_gens": total,
            "est_usd": round(total * 0.05, 2),
            "note": "nano-banana-pro ~$0.05/image; confirm rate in your kie.ai dashboard."}


async def _cmd_run(spec, outdir):
    _load_env()
    from shared.clients.image_client import ImageClient
    ic = ImageClient()
    cast_url = spec.get("cast_url")
    if not cast_url and spec.get("cast_prompt"):
        print("Generating cast sheet ...", flush=True)
        res = await ic.generate_and_wait(prompt=spec["cast_prompt"],
                                         aspect_ratio=spec.get("aspect", "16:9"),
                                         model=Models.IMAGE_THUMBNAIL)
        cast_url = res[0] if res else None
        if not cast_url:
            print("cast sheet generation failed"); sys.exit(1)
        os.makedirs(outdir, exist_ok=True)
        _download(cast_url, os.path.join(outdir, "0_cast_sheet.png"))
        print(f"  cast sheet: {cast_url}", flush=True)
    if not cast_url:
        print("spec needs cast_url or cast_prompt"); sys.exit(1)

    out = await run_coverage(
        beat_text=spec.get("beat_text", ""), cast_url=cast_url, image_client=ic, outdir=outdir,
        video_title=spec.get("video_title", ""), story_bible=spec.get("story_bible"),
        beat_scenes=spec.get("beat_scenes"), env_url=spec.get("env_url"),
        image_prompts=spec.get("image_prompts"), directive_text=spec.get("directive_text"),
        max_moments=spec.get("max_moments", 3), aspect=spec.get("aspect", "16:9"))
    print(json.dumps({k: v for k, v in out.items() if k != "moments"}, indent=2))
    print(f"=== saved to {outdir} ===")


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    cmd = sys.argv[1]
    spec = json.load(open(sys.argv[2]))
    if cmd == "estimate":
        print(json.dumps(_moments_estimate(spec), indent=2))
    elif cmd == "run":
        if len(sys.argv) < 4:
            print("usage: coverage.py run <spec.json> <outdir>"); sys.exit(1)
        asyncio.run(_cmd_run(spec, sys.argv[3]))
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
