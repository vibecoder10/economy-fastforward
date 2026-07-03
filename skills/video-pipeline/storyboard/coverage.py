"""Coverage storyboard generator (Phase 1 of the Seedance pipeline plan).

Coverage = per narrative MOMENT, several matched camera angles of the SAME instant
(a wide master + tighter/alternate angles) that cut together like a multi-camera shoot.
This is the content-engine beats/coverage approach ported into StoryEngine.

The trick that makes angles match: generate the moment's MASTER frame anchored on the
cast sheet, then generate each ANGLE anchored on BOTH the cast sheet AND the master frame,
told "only the camera angle changes." Same call the 3x3 grid path already uses
(image_client.generate_with_reference) — so this touches neither image_client.py nor
pipeline_executor.py.

STATUS (2026-06-24): this IS the live image path. The chat auto-build and the Scenes-page
"pictures"/"generate all pictures" buttons reach run_coverage via
scripts/coverage_to_app.py:generate_coverage_for_video. The old 3x3 grid flow
(run_storyboard_images / generate_contact_sheet) is being retired (GOAL v2 Phase 0); do not
mistake it for the live path. Most of the director machinery (env refs, per-shot durations,
camera motion prompts, the closed-cast validator) still lives on the old grid path and is
being ported INTO this coverage flow in GOAL v2 Phases 5-9.

  coverage.py estimate <spec.json>
  coverage.py run <spec.json> <outdir>

A locked cast (cast_url) wins; with none, a cast sheet is auto-built from the story bible
(or an explicit cast_prompt) so coverage always has an anchor to lock characters to.

spec.json (see proof_spec.json): cast_url OR cast_prompt OR story_bible; beat_text OR
directive_text; optional video_title / beat_scenes / env_url / image_prompts / max_moments / aspect.
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

# Max image generations in flight at once across a whole scene's coverage. Moments and
# the angles within a moment draw concurrently (master-first is still enforced per moment);
# this caps the total so we don't trip Kie rate limits. Tune via env if needed.
_COVERAGE_CONCURRENCY = int(os.getenv("COVERAGE_CONCURRENCY", "5"))


# =============================================================================
# Directive — per moment, a master + matched angles of the same instant
# =============================================================================

def _coverage_system_prompt(profile, max_moments: int, angles_min: int, angles_max: int) -> str:
    cg = profile.color_grade
    # angles_min == 0 = the RESTRAINED shape (e.g. the bilingual echo format):
    # an angle must earn its place, master-only is the default.
    motivated_rule = "" if angles_min > 0 else """
6) ANGLES ARE EARNED, NOT DEFAULT. Add an ANGLE only when the moment needs it: a listener's \
REACTION to a line, a DETAIL or REVEAL the narration points at (an object, a clock, hands), an \
emotional turn on a face, or a bridge into a new location. A plain teaching or transit moment is \
MASTER-ONLY. Never add an angle just for variety."""
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
2) The VISUAL BIBLE (if provided) is BINDING and is the ONLY source of how each character looks. In \
EVERY shot's description, restate that character's exact appearance VERBATIM from the bible — same \
wardrobe and colors, same hair, same face, same creature scale-colour/wings/eyes. NEVER paraphrase, \
swap, or add: do NOT turn plate armour into leather, do NOT add a helmet/cloak/accessory the bible \
does not list, do NOT recolour or resize the creature. If the narration implies a different look, \
the bible STILL wins. The goal is an identical character in every single panel.
3) Within a moment every angle is the SAME instant — identical wardrobe, props, blocking, light. \
Only framing/angle/lens changes. Angles must be genuinely DISTINCT (different shot size AND a \
different visual focus: face vs hands vs object), never near-duplicate zooms of one framing.
4) Across moments keep continuity: same characters, consistent palette and light per location.
5) DIALOGUE = ONE SPEAKER PER MOMENT, ASSIGNED HERE. A clip can only lip-sync one character, so plan \
ONE moment per speaker TURN (each time the speaker changes, that is a new moment), IN SCRIPT ORDER, \
covering EVERY spoken line exactly once. For a speaking moment, put the spoken line on its own \
`LINE:` row right under the MOMENT header — `LINE: <Speaker> | "<exact words, verbatim from the \
SCENE DIALOGUE>"` — and the MASTER must FRAME that speaker delivering it. A run of consecutive \
sentences by the SAME speaker may share one moment's LINE. NEVER put two different speakers in one \
moment. A speaking moment can be JUST a master (no ANGLE). Silent moments (establishing wide, \
insert, cutaway, reaction) have NO `LINE:` row — add a few for visual variety.{motivated_rule}
</rules>

<output_format>
Output ONLY the coverage plan, nothing else. For each moment:

[MOMENT n | one-line description of what happens]
LINE: <Speaker> | "<exact spoken words>"   (ONLY for a speaking moment; omit entirely if silent)
- MASTER [shot_type]: full visual description — subjects with exact appearance, environment, \
blocking, lighting. This is the widest / establishing framing of the moment.
- ANGLE [shot_type]: same instant, different camera — the new framing and what it emphasises.
- ANGLE [shot_type]: ...

shot_type is one of: {SHOT_TYPES}.
Give each moment ONE MASTER plus {angles_min}-{angles_max} ANGLES.
Plan up to {max_moments} moments from the narration below; pick the moments that carry the scene.
Describe every person by APPEARANCE ONLY — height, build, hair, clothing — never by age words \
(no kid/child/boy/girl/teen or ages like "7-year-old"); the image model rejects prompts that \
mention minors. Write "short character with curly brown hair in a red hoodie", not "a young boy".
</output_format>"""


# Writers emit markdown-bold speaker labels (`**Marco:** ¡Espera!`) — normalize
# to plain `Marco:` before parsing or the turn checklist comes back empty and a
# dialogue scene plans as narration. Covers **Name:** / **Name**: / *Name:*.
_BOLD_SPEAKER_RE = re.compile(
    r"(?m)^(\s*)\*{1,3}\s*([A-Z][A-Za-z .'-]{0,24})\s*(?::\s*\*{1,3}|\*{1,3}\s*:)\s*")


def _scene_turns(beat_text: str):
    """Ordered [(speaker, text)] dialogue turns from a scene's narration. Used to
    hand the planner an exact turn checklist, and (via the backend's
    _dialogue_turns alias) to size the shot budget and reconcile stored lines —
    ONE splitter everywhere, or the checklist and the reconcile disagree.

    Only ADJACENT same-speaker lines merge into one turn. The same speaker
    re-entering after narration is a NEW turn: in the echo format the narrator
    teaches between those lines, so gluing them put two story beats — sometimes
    two locations — into one speaking shot (found live: Marco's cafeteria answer
    and his street-chaos line stamped onto a single classroom clip)."""
    out = []
    separated = True  # narration (or scene start) breaks a same-speaker run
    for line in _BOLD_SPEAKER_RE.sub(r"\1\2: ", beat_text or "").splitlines():
        m = re.match(r"^\s*([A-Z][A-Za-z .'-]{0,24}):\s+(\S.*)$", line)
        if not m:
            if line.strip():
                separated = True
            continue
        spk, txt = m.group(1).strip(), m.group(2).strip()
        if out and not separated and out[-1][0].lower() == spk.lower():
            out[-1] = (out[-1][0], f"{out[-1][1]} {txt}")
        else:
            out.append((spk, txt))
        separated = False
    return out


def _coverage_user_prompt(beat_text, video_title, story_bible, beat_scenes, image_prompts) -> str:
    parts = [f'Plan cinematic COVERAGE for "{video_title or "this scene"}".',
             f"\nScene narration:\n{beat_text.strip()}"]
    bible = _format_story_bible_for_beat(story_bible, beat_scenes or [])
    if bible:
        parts.append(f"\n--- VISUAL BIBLE (binding) ---\n{bible}\n--- END VISUAL BIBLE ---")
    if image_prompts:
        listed = "\n".join(f"  - {p}" for p in image_prompts if p)
        parts.append(f"\n--- EXISTING SHOT IDEAS (use as the moments to cover) ---\n{listed}")
    turns = _scene_turns(beat_text)
    if turns:
        listed = "\n".join(f'T{i+1} {spk}: "{txt}"' for i, (spk, txt) in enumerate(turns))
        parts.append(
            f"\n--- DIALOGUE TURNS ({len(turns)}) — make EXACTLY ONE speaking moment for EACH, "
            f"IN THIS ORDER, its MASTER framing that speaker and a LINE: row with these EXACT words. "
            f"Cover all {len(turns)}: skip none, merge none across speakers, change no words. Add a "
            f"few SILENT moments (establishing/insert) around them for variety ---\n{listed}")
    return "\n".join(parts)


async def generate_coverage_directive(
    beat_text, video_title, profile, story_bible, beat_scenes, image_prompts,
    max_moments=3, angles_min=2, angles_max=4, anthropic_client=None, model=None,
) -> str:
    """Run Claude to produce the coverage plan text. Returns the raw directive.
    model: pass a valid model id for a DIRECT Anthropic client (its built-in default can be
    stale); leave None to use the client's own default (e.g. the Kie-routed market model)."""
    if anthropic_client is None:
        from shared.clients.anthropic_client import AnthropicClient
        anthropic_client = AnthropicClient()
    kwargs = dict(
        prompt=_coverage_user_prompt(beat_text, video_title, story_bible, beat_scenes, image_prompts),
        system_prompt=_coverage_system_prompt(profile, max_moments, angles_min, angles_max),
        max_tokens=6000, temperature=0.7,
    )
    if model:
        kwargs["model"] = model
    return await anthropic_client.generate(**kwargs)


# =============================================================================
# Parser
# =============================================================================

_MOMENT_RE = re.compile(r"\[MOMENT\s+(\d+)\s*\|\s*([^\]]*)\]", re.IGNORECASE)
# Tolerant of how the LLM writes the shot line: "- MASTER [WS]:", "- MASTER WS:",
# or multi-word "- ANGLE INSERT ECU:" (brackets optional, shot type 1+ words, colon required).
_SHOT_RE = re.compile(
    r"-\s*\*{0,2}\s*(MASTER|ANGLE)\s*\[?\s*([A-Za-z][\w /-]*?)\s*\]?\s*\*{0,2}\s*:\s*(.+?)"
    r"(?=\n\s*-\s*\*{0,2}\s*(?:MASTER|ANGLE)\b|\n\s*\*{0,2}\s*\[MOMENT|\Z)",
    re.IGNORECASE | re.DOTALL,
)
# The line the planner assigned to a speaking moment: `LINE: Dad | "exact words"`.
_LINE_RE = re.compile(r'(?im)^\s*\*{0,2}\s*LINE\s*:\s*([^|"\n]+?)\s*\|\s*"([^"]+)"')


def parse_coverage(directive_text: str) -> list[dict]:
    """Parse the coverage plan into moments. Each moment: {moment_number, summary,
    master:{shot_type,description}, angles:[...], speaker, line}. speaker/line are
    set only for a speaking moment (the planner assigns dialogue at draw time)."""
    heads = list(_MOMENT_RE.finditer(directive_text))
    moments: list[dict] = []
    for i, h in enumerate(heads):
        block = directive_text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(directive_text)]
        master, angles = None, []
        lm = _LINE_RE.search(block)
        speaker = lm.group(1).strip() if lm else None
        line = lm.group(2).strip() if lm else None
        for m in _SHOT_RE.finditer(block):
            shot = {"shot_type": m.group(2).strip().upper(), "description": m.group(3).strip()}
            if m.group(1).upper() == "MASTER" and master is None:
                master = shot
            else:
                angles.append(shot)
        # A moment needs a master; angles are optional. A single-speaker dialogue
        # beat is often just ONE master shot of the speaker (one line = one shot,
        # one speaker per shot) — forcing an angle there bloated frame count and
        # made the writer cram two speakers onto one shot when lines ran out.
        if master:
            moments.append({"moment_number": int(h.group(1)), "summary": h.group(2).strip(),
                            "master": master, "angles": angles, "speaker": speaker, "line": line})
    return moments


# =============================================================================
# Image generation — the reference-chaining port
# =============================================================================

def _url_of(result):
    return result.get("url") if isinstance(result, dict) else result


# Anchoring an angle on the master frame makes the model preserve the master's
# subject placement and, for tight recomposes onto a face, ADD a new foreground
# person instead of moving the camera onto the existing one (seen live: a
# medium close-up invented a second rider). This guard pins it to one subject.
_SAME_SUBJECT = (
    " This is the SAME moment from a different camera — match the lighting, wardrobe, staging and "
    "setting of the attached reference exactly; only the camera angle and framing change. Keep the "
    "EXACT same character(s) from the reference and add NO new people: if the reference shows one "
    "rider, this frame shows that same single rider recomposed closer, never a second person.")

# Without an explicit style lock, nano-banana holds the reference's style on wide shots but
# drifts to 2D illustration/painting on tight recomposes (seen live: a photoreal MCU came out
# cartoonish). Mirror the proven STYLE LOCK from the 3x3 grid path (generate_contact_sheet):
# the cast sheet's rendering style is the single source of truth, so a photoreal cast → photoreal
# frames; an animated cast → animated frames. Applied to EVERY frame, master and angles.
_STYLE_LOCK = (
    " STYLE LOCK: render in the EXACT same art style and rendering quality as the attached "
    "reference image(s). If the reference is a photoreal / live-action / 3D-CG render, this frame "
    "MUST be equally photoreal and realistic — never switch to 2D illustration, painting, cartoon "
    "or anime, and never change the art style or rendering between frames. "
    # A speaking moment's description mentions the spoken words — GPT Image 2
    # drew them as an English speech bubble on live frames (2026-07-03). A
    # character can be MOUTHING words; the words themselves never appear.
    "NEVER draw speech bubbles, dialogue balloons, captions or subtitles; on-screen text or "
    "lettering only if this shot's description explicitly asks for it.")


async def _gen_ref(image_client, prompt, refs, aspect, resolution, attempts=2):
    """Generate one frame via GPT Image 2 (gpt-image-2-image-to-image — our main model; holds the
    cast's identity from the reference sheet far better than nano-banana), with a light retry.
    ponytail: retry only covers transient None/502; a moderation 400 also returns None and may not
    recover — that frame is then skipped (coverage degrades to fewer angles rather than failing)."""
    for i in range(attempts):
        url = _url_of(await image_client.generate_thumbnail_gpt2(prompt, refs, aspect))
        if url:
            return url
        await asyncio.sleep(2 * (i + 1))
    return None


async def generate_coverage_frames(moment, cast_url, image_client, profile,
                                   env_url=None, aspect="16:9", resolution="2K", sem=None) -> list[dict] | None:
    """Master frame (anchored on cast) -> each angle (anchored on cast + master).
    Returns frames [{role, shot_type, description, url}] or None if the master fails.
    The master MUST be drawn first (angles reference it), but the angles only depend on
    the master, not on each other — so they draw in PARALLEL. `sem` caps total Kie gens."""
    # cast_url may be one URL or a LIST (e.g. the locked per-character 4-view sheets).
    cast_refs = list(cast_url) if isinstance(cast_url, list) else [cast_url]
    base = cast_refs + ([env_url] if env_url else [])
    sem = sem or asyncio.Semaphore(1)  # no semaphore passed => serial fallback

    async def _gen(prompt, refs):
        async with sem:
            return await _gen_ref(image_client, prompt, refs, aspect, resolution)

    m = moment["master"]
    master_prompt = build_image_prompt_from_keyframe({"composition": m["description"]}, profile) + _STYLE_LOCK
    master_url = await _gen(master_prompt, base)  # master first — angles anchor on it
    if not master_url:
        return None
    frames = [{"role": "master", "shot_type": m["shot_type"], "description": m["description"], "url": master_url}]
    angle_refs = cast_refs + [master_url] + ([env_url] if env_url else [])

    async def _angle(a):
        ap = build_image_prompt_from_keyframe({"composition": a["description"]}, profile) + _SAME_SUBJECT + _STYLE_LOCK
        url = await _gen(ap, angle_refs)
        return {"role": "angle", "shot_type": a["shot_type"], "description": a["description"], "url": url} if url else None

    # All angles share the same master ref → draw them concurrently (capped by sem).
    angle_frames = await asyncio.gather(*[_angle(a) for a in moment["angles"]])
    frames.extend([f for f in angle_frames if f])
    return frames


def _download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


def cast_prompt_from_story_bible(story_bible, profile) -> str | None:
    """Build a cast-sheet image prompt from the story bible's characters, so a video
    with no locked cast can still anchor coverage. Returns None if there's nothing to
    build from (caller then needs an explicit cast_url or cast_prompt)."""
    if not story_bible:
        return None
    chars = story_bible.get("characters") or []
    lines = []
    for c in chars:
        cid = (c.get("id") or "character").replace("_", " ")
        look = c.get("costume") or c.get("description") or ""
        if look:
            lines.append(f"{cid.upper()}: {look}")
    if not lines:
        return None
    return (f"Character reference cast sheet. {profile.visual_style_directive} "
            f"A clean reference sheet on a neutral grey background showing each character "
            f"full-body, labeled with their name, with identical lighting and art style "
            f"across all of them: " + " | ".join(lines) +
            ". No text other than the character name labels.")


async def resolve_cast_url(cast_url, image_client, *, cast_prompt=None, story_bible=None,
                           profile=None, aspect="16:9", outdir=None) -> str | None:
    """A locked cast wins; otherwise auto-build a cast sheet (from cast_prompt, else the
    story bible) so coverage always has an anchor. Returns the cast URL or None."""
    if cast_url:
        return cast_url
    cp = cast_prompt or cast_prompt_from_story_bible(story_bible, profile or load_profile({}))
    if not cp:
        return None
    print("No locked cast — auto-building a cast sheet (GPT Image 2) ...", flush=True)
    r = await image_client.generate_scene_image_gpt(cp, None, aspect)  # gpt-image-2 text-to-image
    url = r.get("url") if isinstance(r, dict) else r
    if url and outdir:
        try:
            _download(url, os.path.join(outdir, "0_cast_sheet.png"))
        except Exception:
            pass
    if url:
        print(f"  cast sheet: {url}", flush=True)
    return url


def enforce_shot_budget(moments: list, max_moments: int, angles_max: int,
                        max_frames: int = None) -> list:
    """HARD shot budget (D1): the directive prompt ASKS for at most max_moments
    and angles_max angles, but the planner is an LLM and overshoots (observed
    live: 17 moments / 35 frames against a 12/0 budget). Enforce in code BEFORE
    any drawing spend: trim extra angles per moment, then drop tail moments past
    the cap. Dialogue lines are never lost — the caller's reconcile folds
    overflow turns onto the last speaking shot.

    max_frames (optional) is a TOTAL frame ceiling on top of the per-moment
    caps (Ryan's channel pacing rule, e.g. ≤40 shots for a ~2-min film):
    angles are stripped from the tail moments first — masters (the lip-sync
    units and story beats) are never sacrificed for an angle."""
    planned = sum(1 + len(m.get("angles") or []) for m in moments)
    for m in moments:
        if isinstance(m.get("angles"), list) and len(m["angles"]) > angles_max:
            m["angles"] = m["angles"][:angles_max]
    if len(moments) > max_moments:
        moments = moments[:max_moments]
        for i, m in enumerate(moments, start=1):
            m["moment_number"] = i
    if max_frames:
        total = sum(1 + len(m.get("angles") or []) for m in moments)
        for m in reversed(moments):
            while total > max_frames and m.get("angles"):
                m["angles"].pop()
                total -= 1
        while total > max_frames and len(moments) > 1:
            moments.pop()  # masters-only still over the ceiling — drop tail moments
            total -= 1
    budgeted = sum(1 + len(m.get("angles") or []) for m in moments)
    if budgeted < planned:
        print(f"  [budget] planner wanted {planned} frames — trimmed to {budgeted} "
              f"(max {max_moments} moments, {angles_max} angles each"
              + (f", {max_frames} frames total" if max_frames else "") + ")", flush=True)
    return moments


async def run_coverage(beat_text, image_client, *, outdir, cast_url=None, cast_prompt=None,
                       video_title="", profile=None, story_bible=None, beat_scenes=None,
                       env_url=None, image_prompts=None, directive_text=None,
                       anthropic_client=None, directive_model=None,
                       max_moments=3, angles_min=2, angles_max=4, max_frames=None,
                       aspect="16:9", resolution="2K") -> dict:
    """Build coverage for one scene/beat: directive -> parse -> matched frames per moment.
    A locked cast (cast_url) wins; otherwise a cast sheet is auto-built from the story
    bible (or cast_prompt) so coverage always has something to lock characters to.
    Saves frames + coverage.json locally with angle/shot-type metadata. No DB writes
    (storing into Image records is Phase 2, where the animator consumes them)."""
    profile = profile or load_profile({})
    os.makedirs(outdir, exist_ok=True)
    cast_url = await resolve_cast_url(cast_url, image_client, cast_prompt=cast_prompt,
                                      story_bible=story_bible, profile=profile,
                                      aspect=aspect, outdir=outdir)
    if not cast_url:
        return {"error": "no cast: provide cast_url, cast_prompt, or a story_bible with characters"}
    if directive_text is None:
        directive_text = await generate_coverage_directive(
            beat_text, video_title, profile, story_bible, beat_scenes, image_prompts or [],
            max_moments=max_moments, angles_min=angles_min, angles_max=angles_max,
            anthropic_client=anthropic_client, model=directive_model)
    with open(os.path.join(outdir, "directive.txt"), "w") as f:
        f.write(directive_text)

    moments = parse_coverage(directive_text)
    if not moments:
        return {"error": "no moments parsed from directive", "directive_chars": len(directive_text)}
    moments = enforce_shot_budget(moments, max_moments, angles_max, max_frames=max_frames)

    # Draw all moments CONCURRENTLY (each: master first, then its angles in parallel),
    # with one shared semaphore capping total in-flight Kie image gens. Collapses ~12
    # strictly-serial frames into ~2 sequential steps — scene coverage goes from ~20 min
    # to a few minutes. Set COVERAGE_CONCURRENCY to tune.
    sem = asyncio.Semaphore(_COVERAGE_CONCURRENCY)
    moment_results = await asyncio.gather(*[
        generate_coverage_frames(moment, cast_url, image_client, profile,
                                 env_url=env_url, aspect=aspect, resolution=resolution, sem=sem)
        for moment in moments
    ])

    result_moments, frame_total = [], 0
    for moment, frames in zip(moments, moment_results):
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

    out = {"video_title": video_title, "cast_url": cast_url, "moments": result_moments,
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
    seed = 0 if spec.get("cast_url") else 1  # cast sheet auto-built when none is locked
    total = frames + seed
    return {"moments": mm, "frames_per_moment": per, "image_gens": total,
            "est_usd": round(total * 0.05, 2),
            "note": "nano-banana-pro ~$0.05/image; confirm rate in your kie.ai dashboard."}


async def _cmd_run(spec, outdir):
    _load_env()
    from shared.clients.image_client import ImageClient
    out = await run_coverage(
        beat_text=spec.get("beat_text", ""), image_client=ImageClient(), outdir=outdir,
        cast_url=spec.get("cast_url"), cast_prompt=spec.get("cast_prompt"),
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
