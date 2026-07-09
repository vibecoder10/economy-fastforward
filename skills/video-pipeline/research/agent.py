"""
Research Agent — Standalone deep research module for the video pipeline.

Performs deep thematic research on a topic and produces a structured
research_payload that feeds directly into the brief_translator pipeline.

This module was extracted during Pipeline Unification (Story 0) to serve
as the single source of deep research for all video ideas.

Usage (standalone):
    python research_agent.py --topic "Why the US Dollar Could Collapse by 2030"

Usage (imported):
    from research.agent import ResearchAgent, run_research

    agent = ResearchAgent(anthropic_client)
    payload = await agent.research("Why the US Dollar Could Collapse by 2030")
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from shared.clients.narrative_extractor import extract_narrative_fields
from orchestrator.pipeline_constants import IdeaFields, Models, CURIOSITY_GAP_ENABLED
from shared.json_utils import parse_json_response

# Curiosity gap imports (lazy loaded to avoid circular deps at module level)
if CURIOSITY_GAP_ENABLED:
    from title_idea.curiosity_gap.gap_title_engine import GapTitleEngine
    from autopilot.learning.pattern_library import PatternLibrary

logger = logging.getLogger(__name__)


# === Title Intelligence System ===

def _load_title_patterns() -> dict:
    """Load the title pattern library from title_patterns.json."""
    patterns_path = Path(__file__).resolve().parent.parent / "title_patterns.json"
    if not patterns_path.exists():
        raise FileNotFoundError(f"title_patterns.json not found at {patterns_path}")
    with open(patterns_path) as f:
        return json.load(f)


def _build_title_formulas_text(patterns: dict) -> str:
    """Build a text summary of master formulas for the title generation prompt.

    Legacy PD formulas are excluded from primary generation — only MF formulas are used.
    """
    lines = []
    for f in patterns.get("master_formulas", []):
        lines.append(
            f"- {f['id']}: {f['name']} — Template: \"{f['template']}\" "
            f"(Tier: {f.get('performance_tier', '?')}, Best for: {f.get('best_for', '?')})"
        )
        examples = f.get("examples", [])
        if examples:
            lines.append(f"  Examples: {'; '.join(examples[:2])}")
    return "\n".join(lines)


def _build_scoring_rules_text(patterns: dict) -> str:
    """Build a text summary of the scoring rules for prompts."""
    rules = patterns.get("scoring_rules", {})
    lines = []
    for c in rules.get("criteria", []):
        lines.append(f"- {c['name']} (weight: {c['weight']}): {c['rule']}")
    hard_rules = rules.get("hard_rules", [])
    if hard_rules:
        lines.append("\nHARD RULES:")
        for r in hard_rules:
            lines.append(f"- {r}")
    return "\n".join(lines)


# === Cinematic Writer Guidance Generator ===

async def _generate_cinematic_direction(
    anthropic_client,
    payload: dict,
) -> str:
    """Generate scene-specific writer guidance from research payload.

    Uses Claude Haiku to create cinematic direction that tells the
    scriptwriter WHO, WHERE, WHAT, and the MICRO-INSIGHT for each act.
    This replaces the old approach of just copying the thesis.

    Args:
        anthropic_client: AnthropicClient instance
        payload: Research payload dict with executive_hook, character_dossier,
                 historical_parallels, psychological_angles, fact_sheet,
                 framework_analysis

    Returns:
        Cinematic direction string (under 200 words), or empty string on failure
    """
    # Extract first 5 facts from fact_sheet
    fact_sheet = payload.get("fact_sheet", "")
    facts_lines = [l.strip() for l in fact_sheet.split("\n") if l.strip()][:5]
    key_facts = "\n".join(facts_lines) if facts_lines else "(no facts available)"

    prompt = f"""You are a cinematographic director planning a 12-15 minute animated documentary.
Using the research below, write scene direction for the scriptwriter — one paragraph per act.

For each act, specify:
- WHO (the character type for this act)
- WHERE (specific physical location from research)
- WHAT (one vivid action moment)
- THE MICRO-INSIGHT (a single quotable truth for this act)

ACT STRUCTURE (follow this character progression):
- Act 1: ORDINARY PERSON — viewer surrogate experiencing the situation
- Act 2: OPERATOR — someone doing the work on the ground
- Act 3: ARCHITECT — the system designer or strategist
- Act 4: PROPHET — delivers the apex insight (the "why it all matters" moment)
- Act 5: RETURN TO ORDINARY PERSON — how the system affects regular people
- Act 6: RETURN TO OPERATOR — what practitioners do next

FRAMEWORK ANGLE: {payload.get("framework_analysis", "")}

RESEARCH HOOK: {payload.get("executive_hook", "")}

CHARACTER DOSSIER: {payload.get("character_dossier", "")}

HISTORICAL PARALLELS: {payload.get("historical_parallels", "")}

KEY FACTS:
{key_facts}

Format as flowing direction, not templates.
Example: "Act 1: We're in a shipping container at Long Beach — a trucker checks his phone, delivery canceled. Micro-insight: 'When containers stop moving, shelves go empty.' Act 2: At Shenzhen port, a logistics coordinator reroutes 40 ships..."

Keep it under 200 words. No headers, no bullet points, just cinematic direction with micro-insights."""

    try:
        result = await anthropic_client.generate(
            prompt=prompt,
            model=Models.CLAUDE_HAIKU,
            max_tokens=300,
            temperature=0.7,
        )

        if result and len(result.strip()) > 50:
            logger.info(f"Generated cinematic direction ({len(result)} chars)")
            return result.strip()

    except Exception as e:
        logger.warning(f"Cinematic direction generation failed: {e}")

    return ""


TITLE_GENERATION_PROMPT = """\
You are the title strategist for this YouTube channel. Write titles that fit \
the channel's niche and audience — niche-agnostic craft, not a fixed subject.

TOPIC DATA:
- Headline: {headline}
- Key Entities: {entities}
- Hook/Thesis: {thesis}
- Angle (optional, may be blank): {framework}

TITLE FORMULA LIBRARY:
{formulas}

SCORING CRITERIA:
{scoring_rules}

WHAT MAKES A TITLE WORK (study these principles, not a single niche):
- Curiosity gap: it sits between what the viewer already knows and what they
  want to know — specific enough to be answerable, surprising enough to click.
- Specificity: name the real subject, number, place, or detail. A concrete noun
  out-clicks a vague category every time.
- Honesty: the title is a promise the video must keep. No bait-and-switch.

TASK:
Generate exactly 3 title candidates. Each must use a DIFFERENT formula from the \
library. For each:
1. Write the title (MAXIMUM 55 characters. Ideal is 35-50. Count every character.)
2. Identify which formula ID you used (e.g., MF-0, MF-2)
3. Score it 0-100 using the weighted criteria
4. Write 1 sentence explaining why this angle works
5. Generate a matching 2-4 word thumbnail line (short, punchy, no "YOU/YOUR")

HARD RULES:
1. MAXIMUM 55 characters. HARD CEILING. Under 45 is ideal.
2. Front-load the hook: the most compelling word and the specific subject appear
   early, before mobile truncation cuts the title off.
3. Be specific — name the real subject, not a vague category or empty hype word.
4. NEVER use "YOU" or "YOUR" — this is about the subject, not self-help.
5. NEVER use commands (NEVER, STOP, DON'T) — no imperatives.
6. NEVER use ALL CAPS words except genuine acronyms.
7. No em dashes (—), no parenthetical asides, no pipe separators (|).
8. No empty cleverness. The subject itself is interesting. State what the video
   actually delivers.
9. Declarative statements only. No question marks unless genuinely unanswered.
10. The 3 titles should offer genuinely different angles, not variations of the
    same idea.

Pick the framing the channel's niche actually rewards — do NOT force crisis or \
threat language onto a niche that doesn't want it.

Respond ONLY in this JSON format (no markdown, raw JSON):
{{
  "candidates": [
    {{
      "title": "...",
      "formula_id": "MF-X",
      "score": 85,
      "rationale": "...",
      "thumbnail_text": "..."
    }}
  ],
  "recommended_winner": 0
}}
"""


TITLE_REFINEMENT_PROMPT = """\
You are refining the title for a video. \
The script is now written and you have access to the actual content.

CURRENT TITLE: {current_title}
ANGLE (optional, may be blank): {framework}

SCRIPT CONTENT (all scenes):
{script_text}

TITLE FORMULA LIBRARY:
{formulas}

SCORING CRITERIA:
{scoring_rules}

WHAT MAKES A TITLE WORK (apply across any niche):
- Curiosity gap, specificity (real subject/number/detail, not vague category),
  and honesty (the title is a promise the video keeps).

YOUR TASK:
The current title was a working title generated before the script existed. \
Now that the script is written, you can see the ACTUAL most compelling details.

Step 1: Extract from the script:
- The single most surprising fact, number, or data point
- The most specific moment, mechanism, or technique shown
- The strongest hook or payoff
- The key concrete nouns (subjects, names, places, things)
- The core idea the video actually delivers

Step 2: Generate 3 NEW title candidates that leverage these specific details. \
Each must use a DIFFERENT formula. The new titles should be MORE specific than \
the working title because you now know what the video actually contains.

Step 3: Score all titles (including the current one) using the criteria.

Step 4: If any new title scores higher than the current title, recommend the switch. \
If the current title is already optimal, say so.

HARD RULES:
1. MAXIMUM 55 characters. HARD CEILING. Under 45 is ideal.
2. Front-load the hook so it survives mobile truncation.
3. Be specific — name the real subject, not a vague category.
4. NEVER use "YOU" or "YOUR".
5. NEVER use commands (NEVER, STOP, DON'T) — no imperatives.
6. NEVER use ALL CAPS words except genuine acronyms.
7. No em dashes (—), no parenthetical asides, no pipe separators (|).
8. Declarative statements only. No question marks unless genuinely unanswered.

When refining the title post-script, prefer SHORTER over LONGER. \
If the working title is 50 characters and a refinement is 55 characters \
but only slightly better, keep the shorter one. Brevity wins.

CRITICAL: The #1 reason titles underperform is vagueness. The script gives you \
specific facts, names, and details — USE THEM. But keep it SHORT.
Example: a flat, vague title scores low; the same idea made specific and \
concrete — the real subject and the real number or detail — scores far higher \
and stays just as short.

Respond ONLY in this JSON format (no markdown, raw JSON):
{{
  "script_extractions": {{
    "best_statistic": "...",
    "best_mechanism": "...",
    "best_hook": "...",
    "proper_nouns": ["..."],
    "hidden_playbook": "..."
  }},
  "candidates": [
    {{
      "title": "...",
      "formula_id": "MF-X",
      "score": 85,
      "rationale": "...",
      "thumbnail_text": "..."
    }}
  ],
  "current_title_score": 70,
  "recommended_winner": 0,
  "should_switch": true
}}
"""


def _parse_title_response(response_text: str) -> dict:
    """Parse JSON title generation response with fallback chain."""
    return parse_json_response(response_text)


async def generate_title_candidates(
    anthropic_client,
    topic_data: dict,
    framework: str,
    model: str = Models.CLAUDE_SONNET,
) -> dict:
    """Generate 3 title candidates using the master formula library.

    Phase 1 of the Title Intelligence System — called at idea generation time.

    Args:
        anthropic_client: AnthropicClient instance
        topic_data: Dict with keys 'headline', 'entities', 'hook', 'thesis'
        framework: Optional niche-neutral angle hint (may be ""); the title
            prompt treats it as optional and never forces a fixed framework.
        model: LLM model to use

    Returns:
        dict with 'winner' (str), 'winner_thumbnail' (str),
        'candidates' (list of dicts with title + score + formula_id)
    """
    patterns = _load_title_patterns()
    formulas_text = _build_title_formulas_text(patterns)
    scoring_text = _build_scoring_rules_text(patterns)

    # Extract entities from topic data
    entities = topic_data.get("entities", "")
    if not entities:
        # Try to infer entities from headline and thesis
        entities = ", ".join(filter(None, [
            topic_data.get("headline", ""),
            topic_data.get("hook", ""),
        ]))

    prompt = TITLE_GENERATION_PROMPT.format(
        headline=topic_data.get("headline", ""),
        entities=entities,
        thesis=topic_data.get("thesis", topic_data.get("hook", "")),
        framework=framework,
        formulas=formulas_text,
        scoring_rules=scoring_text,
    )

    response = await anthropic_client.generate(
        prompt=prompt,
        system_prompt="You are a YouTube title optimization expert. Respond only in valid JSON.",
        model=model,
        max_tokens=2000,
        temperature=0.7,
    )

    result = _parse_title_response(response)
    candidates = result.get("candidates", [])
    winner_idx = result.get("recommended_winner", 0)

    if not candidates:
        logger.warning("Title generation returned no candidates")
        return {
            "winner": topic_data.get("headline", ""),
            "winner_thumbnail": "",
            "candidates": [],
        }

    # Clamp winner index
    winner_idx = max(0, min(winner_idx, len(candidates) - 1))
    winner = candidates[winner_idx]

    return {
        "winner": winner.get("title", ""),
        "winner_thumbnail": winner.get("thumbnail_text", ""),
        "candidates": candidates,
    }


async def refine_title_post_script(
    anthropic_client,
    airtable_client,
    record_id: str,
    model: str = Models.CLAUDE_SONNET,
) -> dict:
    """Phase 2: Refine title using actual script content.

    Fires after script is complete (status = Ready For Voice).

    1. Read the full script from Script table (all scenes for this title)
    2. Extract most surprising details from the actual content
    3. Regenerate 3 titles using the formula library + script specifics
    4. Score and pick winner
    5. Update Video Title if better, archive in Title Candidates

    Args:
        anthropic_client: AnthropicClient instance
        airtable_client: AirtableClient instance
        record_id: Airtable record ID of the idea
        model: LLM model to use

    Returns:
        dict with 'should_switch', 'old_title', 'new_title', 'score',
        'thumbnail_text', 'candidates'
    """
    # Read the idea record
    idea = airtable_client.get_idea(record_id)
    if not idea:
        raise ValueError(f"Idea record {record_id} not found")

    current_title = idea.get(IdeaFields.VIDEO_TITLE, "")
    # Optional angle hint for the title prompt; blank is fine (no forced
    # framework — the title prompt treats {framework} as optional).
    framework = idea.get(IdeaFields.FRAMEWORK_ANGLE, "")

    # Get all script scenes for this video
    scripts = airtable_client.get_scripts_by_title(current_title)
    if not scripts:
        logger.warning(f"No scripts found for '{current_title}', skipping refinement")
        return {"should_switch": False, "old_title": current_title, "candidates": []}

    # Combine all scene text
    script_text = "\n\n".join(
        f"Scene {s.get('scene', '?')}: {s.get('scene_text', '')}"
        for s in sorted(scripts, key=lambda s: s.get("scene", 0))
    )

    # Truncate if too long (keep prompt under token limits)
    if len(script_text) > 15000:
        script_text = script_text[:15000] + "\n\n[... truncated for length ...]"

    patterns = _load_title_patterns()
    formulas_text = _build_title_formulas_text(patterns)
    scoring_text = _build_scoring_rules_text(patterns)

    prompt = TITLE_REFINEMENT_PROMPT.format(
        current_title=current_title,
        framework=framework,
        script_text=script_text,
        formulas=formulas_text,
        scoring_rules=scoring_text,
    )

    response = await anthropic_client.generate(
        prompt=prompt,
        system_prompt="You are a YouTube title optimization expert. Respond only in valid JSON.",
        model=model,
        max_tokens=2000,
        temperature=0.7,
    )

    result = _parse_title_response(response)
    candidates = result.get("candidates", [])
    should_switch = result.get("should_switch", False)
    winner_idx = result.get("recommended_winner", 0)
    current_score = result.get("current_title_score", 0)

    if not candidates:
        logger.warning("Title refinement returned no candidates")
        return {"should_switch": False, "old_title": current_title, "candidates": []}

    winner_idx = max(0, min(winner_idx, len(candidates) - 1))
    winner = candidates[winner_idx]

    # Load existing title candidates from Airtable
    existing_candidates_json = idea.get("Title Candidates", "")
    existing_candidates = []
    if existing_candidates_json:
        try:
            existing_candidates = json.loads(existing_candidates_json)
        except (json.JSONDecodeError, TypeError):
            existing_candidates = []

    # Build updated candidates list
    # Archive the current title with its score
    archived_entry = {
        "title": current_title,
        "formula_id": "original",
        "score": current_score,
        "rationale": "Original/Phase 1 title",
        "thumbnail_text": idea.get("Thumbnail Text", ""),
        "phase": "phase_1",
    }
    # Tag new candidates as phase 2
    for c in candidates:
        c["phase"] = "phase_2"

    all_candidates = existing_candidates + [archived_entry] + candidates

    # Write to Airtable
    update_fields = {
        "Title Candidates": json.dumps(all_candidates),
    }

    if should_switch:
        update_fields[IdeaFields.VIDEO_TITLE] = winner.get("title", "")
        update_fields[IdeaFields.THUMBNAIL_TEXT] = winner.get("thumbnail_text", "")

    airtable_client.update_idea_fields(record_id, update_fields)

    new_title = winner.get("title", "") if should_switch else current_title
    logger.info(
        f"Title refinement for '{current_title}': "
        f"{'SWITCHED to' if should_switch else 'kept'} '{new_title}' "
        f"(score: {winner.get('score', '?')})"
    )

    return {
        "should_switch": should_switch,
        "old_title": current_title,
        "new_title": new_title,
        "score": winner.get("score", 0),
        "thumbnail_text": winner.get("thumbnail_text", ""),
        "candidates": candidates,
    }

# Research prompt template
#
# NEUTRAL last-resort fallback (engine/identity split, Phase 2). This fires only
# when the executor passes no system_prompt_override (i.e. no tenant/engine
# prompt resolved). It is intentionally self-contained — this skill package
# CANNOT import the backend's engine_templates — but it carries the SAME
# universal research craft: go deep / verify before including / cite real
# sources / mark unverified / hand back a structured brief / niche-appropriate
# specificity. No geopolitics, no statistic quota, no incentive-chain exposé
# structure (those belong to a specific channel identity, not the engine).
RESEARCH_SYSTEM_PROMPT = """\
You are a research analyst for a YouTube channel. Your job is to research a
topic deeply and hand back a structured brief the scriptwriter can build a
great video from. Research whatever the video actually needs — the facts, the
context, the examples, the angles — appropriate to this channel's subject and
audience, not a fixed formula.

GO DEEP, NOT SURFACE:
Surface-level summaries are useless to the script stage. Dig past the obvious:
find the specific detail, the precise example, the step that actually matters,
the context most coverage skips. You are building the intellectual foundation
for a video the audience will watch end to end.

VERIFY BEFORE YOU INCLUDE — USE WEB SEARCH:
You have web search available. USE IT to verify facts before you put them in
the brief.
- Search the key claims, names, dates, and figures you intend to use.
- Include only facts you can actually verify; prefer primary or authoritative
  sources.
- Cite a real source for every load-bearing claim.
- If you cannot verify something, keep it only if it earns its place, and
  clearly mark it as unverified — never present a guess as a fact.
- For niche or hard-to-find topics, try several query variations before
  concluding something is unknown.

COMPLETE-ROSTER TITLES ARE A CONTRACT:
If the title promises a complete set — for example "Every...", "All...",
"...Ever Built", "Complete History/List", or a duplicate/parity test — your
first job is not to find an angle. Your first job is to discover the full roster
that the title promises. Do not start writing the thesis until you have built,
cross-checked, and stress-tested that roster.

For machines/vehicles/weapons/programs, search like an archivist, not a casual
summarizer. Use multiple query families before declaring a roster complete:
- exact title and close variants,
- official designation/category pages,
- manufacturer/program lists,
- service/operator inventory or historical-office pages,
- museum/encyclopedia lists,
- prototype/cancelled/experimental designation searches,
- "missing" edge cases such as variants, escort versions, cancelled prototypes,
  interim models, renamed programs, and role-boundary disputes.

Never silently narrow a title. If the title says "Every US Strategic Bomber Ever
Built," do not return only postwar operational bombers unless the title is also
changed. Include production aircraft, prototypes, cancelled-but-built aircraft,
and disputed edge cases unless the roster boundary explicitly excludes them.

SPECIFICITY OVER VAGUENESS — APPROPRIATE TO THE TOPIC:
Concrete beats abstract. Give the real detail — the exact name, the specific
step, the precise figure, the named example — not "significant", "a lot", or
"many". Bring in whatever data and specifics this kind of video genuinely
needs: some topics want hard numbers and dates; a cooking video wants exact
temperatures, times, and ratios; a story or language video wants concrete
scenes, characters, and vocabulary. Match the specificity to the subject —
there is no fixed statistic quota.

HAND BACK A STRUCTURED BRIEF:
Organize the brief so the script stage can use it directly: a clear
headline/angle, the core idea, the verified facts (each with its source), the
most useful context and examples, the angles that would keep the audience
watching, and concrete visual ideas for the imagery. Note honestly where the
evidence is thin or contested."""

COMPLETE_ROSTER_SYSTEM_APPEND = """\

NON-NEGOTIABLE COMPLETE-ROSTER OVERRIDE:
If the topic/title promises a complete set — for example "Every...", "All...",
"...Ever Built", "Complete History/List", or a duplicate/parity test — this
instruction overrides any channel preference for curation, shortlists, or
story-first selection.

For these titles, the candidate universe is the product. Build and cross-check
wide first, before thesis or story selection. Do not return a narrow curated
shortlist. Do not exclude a machine because its story is weaker if it belongs to
the title boundary. Include production machines, built/flown prototypes,
converted variants, special-purpose versions, cancelled-but-built programs,
secret/black programs that were built or credibly fielded, interim models,
renamed programs, and disputed edge cases unless the inclusion boundary explicitly
and defensibly excludes them.

For machine/program topics, search by designation families, program names, role
words, and edge-case language. Aircraft examples: XB/YB/B/FB designations,
prototype, experimental, cancelled, converted, escort, interim, variant,
strategic, heavy, very heavy, bomber, program, built, flown, entered service, and
manufacturer names. Ship examples: hull/class names, laid down, commissioned,
converted, cancelled after construction started, treaty battleship,
battlecruiser, fast battleship, dreadnought. Tanks/vehicles: prototype,
production, conversion, assault gun/tank-destroyer boundary, captured conversion,
secret program. Cross-check against official/service history, manufacturer or
program history, museum/encyclopedia lists, designation/index lists, and
credible specialist references.

Before finalizing the roster, run an explicit adversarial gap-hunt pass. Assume
your first roster missed machines. Search for omissions by designation sequence,
role synonyms, prototype/cancelled terms, converted/special variants, and
program-family neighbors. For every plausible missed candidate you discover,
force it into one of three places: the recommended final roster, a bucketed
operator decision, or excluded_candidates with a concrete source-backed reason.
Do not leave researched machines in narrative prose only.

For broad DvsU-style machine videos, separate discovery from recommendation:
1) gather the widest defensible candidate universe in buckets;
2) recommend the best final documentary roster for the title;
3) make autonomous default decisions for boundary calls instead of waiting for a
human operator. Benchmarks/customer scripts are validation targets, not hard-coded
product boundaries.

If you cannot recommend a defensible final roster, mark roster_contract
INCOMPLETE and list each unresolved/missing candidate. If you can recommend a
final roster, mark roster_contract CONFIRMED and apply your default decisions in
the recommended roster. Boundary calls should be documented in
operator_decision_points for audit only, not treated as a reason to stop. Never
silently narrow a complete-title video into a hidden shortlist.

For complete-roster titles, keep this pass research-only. Do not write script
prose, hooks, act breaks, thumbnail copy, or production-ready narration. The
first pass should gather and validate the roster. A later enrichment pass may add
compact machine facts, and the script stage is responsible for making the final
95-120 word paragraph per machine."""


def _is_complete_roster_topic(topic: str) -> bool:
    """Detect titles where research must discover a complete roster first."""
    import re

    t = str(topic or "").strip().lower()
    return bool(
        re.search(r"\b(every|all)\b", t)
        or "ever built" in t
        or "complete list" in t
        or "complete history" in t
    )


ROSTER_DISCOVERY_PROMPT_TEMPLATE = """\
Research the following topic as a ROSTER DISCOVERY pass only:

<topic>{TOPIC}</topic>

{SEED_URLS_SECTION}
{CONTEXT_SECTION}

This is NOT the script pass and NOT the full documentary brief pass.
Your job is to discover the broad machine/unit candidate universe implied by the
video title, organize it into reusable machine buckets, then recommend the best
final documentary roster/selection for that title. This must work for any vehicle
or machine category: aircraft, ships, submarines, tanks, armored vehicles,
trucks, off-road vehicles, missiles, artillery, spacecraft, weapons platforms,
industrial machines, or any other title-implied machine family. It runs in
autonomous production mode: the customer is not operating the research step, so
you must make defensible default boundary decisions yourself and document them.

Rules:
- First classify the title as one of: complete_roster, ranked_top_n,
  category_explainer, comparison, or other. For top-N/ranked titles, do NOT stop
  at N candidates: build a wider candidate pool, then rank/select. For complete
  titles, prioritize completeness over narrative neatness.
- Search wide first. Return every plausible candidate category even when the
  final recommendation excludes some items. Treat examples in the title/context
  as seeds only, never as the complete boundary.
- After the first roster draft, run a second adversarial gap hunt. Assume the
  first draft missed machines. Search by designation sequence, role synonyms,
  prototype/cancelled language, converted/special variants, and program-family
  neighbors. Promote every plausible find into a bucket, operator decision, or
  source-backed exclusion.
- Do not hard-code one benchmark roster or overfit one customer script. Benchmarks
  are validation checks, not the product path.
- Do not write narration, hooks, act breaks, thumbnail ideas, or final script prose.
- Actively search edge cases: production machines, built/flown/built-and-tested
  prototypes, experimental designations, cancelled-but-built programs,
  secret/black programs, converted variants, escort/support/special-purpose
  versions, interim models, renamed/reclassified programs, predecessor/successor
  families, foreign-built/license-built/locally modified machines used by the
  title-implied country or force, civilian machines militarized in conflict, and
  role-boundary disputes.
- Interpret role words by audience/title intent, not by the narrowest modern
  official label. If a title says strategic bomber, off-road warfare vehicle,
  battleship, tank destroyer, missile truck, submarine class, etc., include
  historical or functional equivalents that viewers would reasonably expect even
  when official terminology changed by era, branch, or country. Do not silently
  discard older, wartime, interim, converted, or doctrinally-adjacent machines
  merely because their official category name was narrower.
- For national or force-level complete titles using words like every/all/ever
  built/complete, use any VIDEO LENGTH / ROSTER PACING PRESSURE context as a
  completeness-pressure heuristic. Anton/DVsU machine-roster benchmarks average
  about 95-120 words per audience-facing machine but about 60 seconds of final
  screen time per machine once VO pacing, pauses, transitions, and visuals are
  included. If the requested length implies about N machines, your candidate
  universe should exceed N by the stated good-measure buffer before final
  filtering, and your final roster should land near N unless sources prove the
  category is genuinely smaller. Do not pad with weak fits; instead, search
  harder, then document why a smaller verified universe is closed if applicable.
- Your gap hunt must explicitly test generic omission classes, not title-specific
  memorized examples: designation/number sequence gaps, prefix/classification
  variants, role synonyms, mission-converted platforms, special-purpose support
  variants, export/license/local-modification variants, predecessor/successor
  names, manufacturer program-family neighbors, and common false positives.
  Do not let any class disappear just because it is a variant; include, bucket,
  or source-backed exclude it explicitly.
- For any machine family with formal designations, trace the full designation
  neighborhood rather than starting at the first famous production model. Search
  earlier numbers, skipped numbers, X/Y/prototype prefixes, production prefixes,
  role prefixes, and variant suffixes. If a designation appears in sequence/index
  sources, it must be visible somewhere in the output with a final placement.
- For complete roster titles, never use “not production” as the only reason to
  exclude a physically built/flown/commissioned candidate. If it was physically
  built and plausibly fits the title's machine category, the default is include
  in the final roster or include as a combined family entry; exclusion requires a
  stronger category-mismatch reason.
- For each candidate, decide: core include, edge-case include, operator decision,
  exclude, or unresolved.
- `unit_roster` must be the recommended final documentary roster: one section per
  audience-facing machine/program, not every subvariant unless the subvariant is
  itself the machine viewers expect to see.
- Also return the wider candidate universe in `machine_discovery_buckets` so the
  operator can see what was found and why boundary calls were made.
- Return `gap_hunt_matrix` showing the follow-up omission hunt: candidate name,
  discovery path/query family, final placement, and reason. This is how the
  operator verifies that edge cases were actively chased instead of missed.
- Default inclusion rule for complete DVsU machine titles: include audience-facing
  built/flown/commissioned/converted machines and historically important built
  prototypes when the title wording can defensibly cover them; exclude pure paper
  studies unless the title explicitly promises never-built/cancelled programs.
- Boundary decisions are not a stop sign. If a candidate is debatable but likely
  valuable to the title promise/audience, apply a default include/exclude call,
  put the result in the roster or exclusions, and document the call in
  operator_decision_points.
- If you can recommend a strong final roster, mark roster_contract CONFIRMED even
  when boundary taste calls exist. Only mark INCOMPLETE when you cannot make a
  defensible recommendation after the gap hunt.
- Keep per-machine notes compact: enough for verification, not a 95-120 word
  script paragraph. Script expansion happens later.

Respond ONLY as raw JSON in this format:

{{
  "research_phase": "roster_discovery",
  "title_classification": "complete_roster/ranked_top_n/category_explainer/comparison/other",
  "title_classification_reason": "Why this title implies that research mode",
  "inferred_inclusion_boundary": "Plain-English boundary inferred from the title before candidate filtering",
  "headline": "{TOPIC}",
  "thesis": "Roster discovery only — final thesis is deferred until enrichment/script.",
  "executive_hook": "Deferred until script stage.",
  "unit_roster": [
    {{
      "name": "Exact machine/program name for the RECOMMENDED final documentary roster",
      "designation": "Short code/designation/hull number/class if applicable",
      "role": "Why it belongs under the title boundary",
      "status": "production/built-prototype/cancelled-built/converted/special-purpose/secret-or-black-program/edge-case",
      "bucket": "core_roster/built_prototypes/converted_or_special_variants/secret_cancelled_or_black_programs/boundary_disputes",
      "built_count": "Exact count or best verified range, with source tag",
      "years": "first flight/service/planned/commissioned years if verified, with source tag",
      "source": "Strongest source tag"
    }}
  ],
  "machine_discovery_buckets": {{
    "core_roster": [{{"name": "Obvious title-fit machine", "why": "why it cleanly belongs", "source": "Source tag"}}],
    "built_prototypes": [{{"name": "Built/flown prototype or prototype ship/vehicle", "why": "why it may deserve a section", "source": "Source tag"}}],
    "converted_or_special_variants": [{{"name": "Converted/special-purpose variant", "why": "why it matters", "source": "Source tag"}}],
    "secret_cancelled_or_black_programs": [{{"name": "Secret/cancelled/black/cancelled-but-built program", "why": "what is verified and why it matters", "source": "Source tag or [unverified]"}}],
    "boundary_disputes": [{{"name": "Candidate with real boundary ambiguity", "decision_needed": "operator/customer call", "source": "Source tag"}}]
  }},
  "recommended_final_roster": ["Ordered list of names/designations from unit_roster"],
  "ranking_logic": "For ranked/top-N titles: how final selections were chosen from the wider pool. For complete roster titles: 'not applicable — completeness prioritized'.",
  "gap_hunt_matrix": [{{"candidate": "Plausible missed machine/program", "discovery_path": "designation sequence / role synonym / prototype search / variant search / program-family neighbor / source cross-check", "final_placement": "unit_roster / machine_discovery_buckets.<bucket> / operator_decision_points / excluded_candidates", "reason": "why it landed there"}}],
  "edge_case_matrix": [{{"edge_case_class": "designation gap / prefix variant / converted variant / special-purpose variant / foreign-built-used-by-target / license-built / renamed-reclassified / predecessor-successor / false-positive", "candidates_checked": ["machine/program"], "coverage_result": "included/bucketed/excluded/unresolved", "reason": "how this class was resolved"}}],
  "operator_decision_points": [{{"question": "Boundary/taste decision documented for audit", "default_recommendation": "include/exclude", "applied_decision": "include/exclude", "options": ["include", "exclude"], "reason": "why this was the autonomous default"}}],
  "roster_contract": "CONFIRMED or INCOMPLETE. State the inclusion boundary and whether the recommended final roster is defensible. In autonomous mode, do not use REVIEW_READY as a stopping state when you can apply defensible default decisions.",
  "roster_audit": {{
    "is_complete_title": true,
    "inclusion_boundary": "Strict inclusion/exclusion rule",
    "search_queries_used": ["exact query #1", "exact query #2", "exact query #3", "exact query #4", "exact query #5", "exact query #6", "exact query #7", "exact query #8"],
    "source_families_crosschecked": ["official/service history", "manufacturer/program history", "museum/encyclopedia list", "designation/index list"],
    "excluded_candidates": [{{"name": "Reviewed but excluded", "reason": "Boundary reason", "source": "Source tag"}}],
    "unresolved_candidates": [{{"name": "Candidate not resolved", "reason": "What still needs verification", "source": "Source tag or [unverified]"}}],
    "confidence": "high/medium/low"
  }},
  "fact_sheet": "Roster-discovery summary only. One compact line per included machine: designation/name — status — built count — years — strongest source tag. No script prose.",
  "source_bibliography": "Every [Source Year] tag used above, one entry each.",
  "counter_arguments": "Boundary disputes and source disagreements only.",
  "historical_parallels": "Deferred until enrichment pass.",
  "framework_analysis": "Deferred until enrichment/script.",
  "character_dossier": "Deferred until enrichment pass unless a named person is needed to verify a roster boundary.",
  "narrative_arc": "Deferred until script stage.",
  "visual_seeds": "Deferred until enrichment/image planning. Do not generate image prompts here.",
  "themes": "Deferred until enrichment/script.",
  "psychological_angles": "Deferred until script stage.",
  "narrative_arc_suggestion": "Deferred until script stage.",
  "title_options": "Deferred until script/SEO stage.",
  "thumbnail_concepts": "Deferred until thumbnail stage."
}}
"""

RESEARCH_PROMPT_TEMPLATE = """\
Research the following topic in depth:

<topic>{TOPIC}</topic>

{SEED_URLS_SECTION}
{CONTEXT_SECTION}

Produce a structured research brief with ALL of the following sections.
Each section should be substantial (200-500 words). Do not skip any section.

Respond in the following JSON format (no markdown code blocks, just raw JSON):

{{
  "headline": "A compelling, specific video title (not generic)",
  "thesis": "The core argument or revelation of this video in 2-3 sentences",
  "executive_hook": "The opening 15-second hook that stops the scroll. Must create immediate curiosity gap.",
  "fact_sheet": "Verified facts with inline source tags. Format EVERY fact as: 'Bread dough proofs fastest at around 27C / 80F [King Arthur Baking 2023].' Use concrete specifics appropriate to the topic — exact names, dates, amounts, steps, measurements, or ratios — EACH with a [Source Name Year] tag immediately after the claim. If a source is uncertain, use [unverified]. Every [Source] tag must match an entry in source_bibliography. Not 'significant growth' but the real, sourced specific. Include as many verified specifics as the topic genuinely needs — there is no fixed quota.",
  "unit_roster": [
    {{"name": "Exact named unit/item/machine/person/case #1", "designation": "short code if applicable", "role": "why it belongs", "status": "production/prototype/cancelled/variant/disputed", "source": "Source tag"}}
  ],
  "roster_contract": "For any title promising 'Every...', 'All...', a complete class list, or a duplicate/parity test, explain the inclusion boundary and confirm the roster is complete. If the research is incomplete, start with INCOMPLETE and list missing categories/items. Never silently narrow the title.",
  "roster_audit": {{
    "is_complete_title": true,
    "inclusion_boundary": "What qualifies and what does not, written as a strict rule",
    "search_queries_used": ["exact query #1", "exact query #2", "exact query #3", "exact query #4", "exact query #5", "exact query #6"],
    "source_families_crosschecked": ["official/service history", "manufacturer/program history", "museum/encyclopedia list", "designation/index list"],
    "excluded_candidates": [{{"name": "candidate reviewed but excluded", "reason": "why it does not fit the boundary", "source": "Source tag"}}],
    "unresolved_candidates": [{{"name": "candidate not resolved", "reason": "what still needs verification", "source": "Source tag or [unverified]"}}],
    "confidence": "high/medium/low"
  }},
  "historical_parallels": "Background, prior examples, or comparable cases that illuminate this topic. Include specific details and outcomes. Provide a few distinct, genuinely relevant examples (omit if a topic has none — do not force them).",
  "framework_analysis": "The mental model or lens that best explains this topic for the audience. What makes it click? Use whatever framing actually fits the subject — a process, a cause-and-effect, a comparison, a story shape — not a fixed theory.",
  "character_dossier": "Key people, characters, or figures involved (if any). For each: name, role, specific actions, motivations, and a visual description for imagery. Omit if the topic has no people.",
  "narrative_arc": "The shape of the video: how it opens, builds, and pays off. Include the specific turning points, reveals, or steps the audience should move through. Let the subject decide the structure.",
  "counter_arguments": "The strongest objections, caveats, or common misconceptions about the thesis. Acknowledge them honestly, then explain how the brief addresses them.",
  "visual_seeds": "Specific visual concepts for AI image generation. Describe scenes, settings, objects, and moods. At least 5 distinct visual concepts.",
  "source_bibliography": "Key sources used — each entry MUST appear at least once as a [Source] tag in the fact_sheet. Format: 'Source Name Year: Full citation or URL'. Example: 'King Arthur Baking 2023: King Arthur Baking Company, Dough Proofing Guide, 2023'. Every source you cite in fact_sheet brackets must have a matching entry here.",
  "themes": "Thematic threads that give the video depth and coherence. Use whatever themes genuinely run through this subject. At least 3 themes.",
  "psychological_angles": "Viewer hooks and what makes this personally relevant to the audience — the curiosities, aspirations, or questions it taps into.",
  "narrative_arc_suggestion": "Recommended overall structure for the video, with a brief description of each part's focus and the feeling it should carry. Use as many parts as the subject wants.",
  "title_options": "3 alternative compelling video titles, each on a new line",
  "thumbnail_concepts": "2-3 thumbnail visual concepts, each with one clear focal point"
}}

IMPORTANT:
- Every fact must be SPECIFIC (real names, details, measurements) — no vague generalizations
- Match the amount of data/specifics to what the topic genuinely needs — there is no fixed number quota
- Examples and parallels must be genuinely ILLUMINATING, not just tangentially related
- The framework must give a real "now it makes sense" insight, not a textbook summary
- Visual seeds must describe SCENES, not abstract concepts
- The hook must create an irresistible curiosity gap in under 15 seconds of speech
- Verify load-bearing claims before including them; mark anything you cannot verify as [unverified]
- For “Every…” / “All…” / complete-roster titles, the `unit_roster` is the promise of the video. Research the full class list before choosing an angle. Do not curate a shortlist unless the title is narrowed to match it.
- For complete-roster titles, `roster_audit.search_queries_used` must show at least 6 genuinely different searches and `source_families_crosschecked` must show at least 3 different source families. If you did not do that work, mark `roster_contract` INCOMPLETE.
- For complete-roster machine/vehicle/program videos, actively look for edge cases: prototypes, experimental designations, cancelled-but-built examples, variants, interim models, escort/special-purpose versions, renamed programs, and role-boundary disputes.
- If a complete-roster title cannot be fully researched, set `roster_contract` to INCOMPLETE, put unresolved items in `roster_audit.unresolved_candidates`, and name the missing categories/items so the UI can block scripting instead of silently producing the wrong video.
"""


def _build_research_prompt(
    topic: str,
    seed_urls: Optional[list[str]] = None,
    context: Optional[str] = None,
) -> str:
    """Build the research prompt with optional seed URLs and context."""
    seed_section = ""
    if seed_urls:
        urls_text = "\n".join(f"- {url}" for url in seed_urls)
        seed_section = f"Use these URLs as starting points for research:\n{urls_text}"

    context_section = ""
    if context:
        context_section = f"Additional context:\n{context}"

    template = ROSTER_DISCOVERY_PROMPT_TEMPLATE if _is_complete_roster_topic(topic) else RESEARCH_PROMPT_TEMPLATE
    return template.format(
        TOPIC=topic,
        SEED_URLS_SECTION=seed_section,
        CONTEXT_SECTION=context_section,
    )


def _parse_research_payload(response_text: str) -> dict:
    """Parse the JSON research payload from Claude's response.

    Handles potential formatting issues (markdown code blocks, etc.)
    Raises json.JSONDecodeError if parsing fails completely.
    """
    payload = parse_json_response(response_text, default=None)
    if payload is None:
        raise json.JSONDecodeError("Failed to parse research payload", response_text, 0)

    # Validate required fields
    required_fields = [
        "headline", "thesis", "executive_hook", "fact_sheet",
        "historical_parallels", "framework_analysis", "character_dossier",
        "narrative_arc", "counter_arguments", "visual_seeds",
        "source_bibliography",
    ]

    missing = [f for f in required_fields if not payload.get(f)]
    if missing:
        logger.warning(f"Research payload missing fields: {missing}")

    return payload


class ResearchAgent:
    """Standalone deep research agent for video production.

    Produces structured research_payload objects that feed into the
    brief_translator pipeline.

    Usage:
        agent = ResearchAgent(anthropic_client)
        payload = await agent.research("Topic here")
    """

    def __init__(
        self,
        anthropic_client,
        model: str = Models.CLAUDE_SONNET,
        system_prompt_override: Optional[str] = None,
    ):
        """Initialize the research agent.

        Args:
            anthropic_client: AnthropicClient instance for LLM calls
            model: Model to use for research (Sonnet for cost, Opus for depth)
            system_prompt_override: Optional tenant override that replaces
                RESEARCH_SYSTEM_PROMPT at the Claude call site.
        """
        self.anthropic = anthropic_client
        self.model = model
        self.system_prompt_override = system_prompt_override

    async def research(
        self,
        topic: str,
        seed_urls: Optional[list[str]] = None,
        context: Optional[str] = None,
    ) -> dict:
        """Run deep research on a topic.

        Args:
            topic: The topic or idea to research
            seed_urls: Optional list of URLs to seed research
            context: Optional additional context

        Returns:
            Structured research_payload dict containing:
                - headline (str)
                - thesis (str)
                - executive_hook (str)
                - fact_sheet (str)
                - historical_parallels (str)
                - framework_analysis (str)
                - character_dossier (str)
                - narrative_arc (str)
                - counter_arguments (str)
                - visual_seeds (str)
                - source_bibliography (str)
                - themes (str)
                - psychological_angles (str)
                - narrative_arc_suggestion (str)
                - title_options (str)
                - thumbnail_concepts (str)
        """
        from shared.clients.anthropic_client import WEB_SEARCH_TOOL

        logger.info(f"Starting deep research on: {topic}")

        prompt = _build_research_prompt(topic, seed_urls, context)

        system_prompt = self.system_prompt_override or RESEARCH_SYSTEM_PROMPT
        if COMPLETE_ROSTER_SYSTEM_APPEND not in system_prompt:
            system_prompt = f"{system_prompt}\n{COMPLETE_ROSTER_SYSTEM_APPEND}"

        tools = [WEB_SEARCH_TOOL]
        if _is_complete_roster_topic(topic):
            tools = [dict(WEB_SEARCH_TOOL, max_uses=8)]

        response = await self.anthropic.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=self.model,
            max_tokens=16000,
            temperature=0.7,
            tools=tools,
        )

        payload = _parse_research_payload(response)
        logger.info(
            f"Research complete: {payload.get('headline', 'Untitled')} — "
            f"{len(payload)} fields populated"
        )

        return payload


def infer_framework_from_research(payload: dict) -> str:
    """Return the niche-neutral analytical angle from a research payload.

    Engine/identity split (Phase 3): this used to force every topic onto one of
    17 hardcoded geopolitics/power frameworks (48 Laws, Machiavelli, Thucydides
    Trap, Sun Tzu, Grand Chessboard, …), defaulting to "48 Laws". That keyword
    map was Power-Doctrine IDENTITY, not universal craft — it would mislabel an
    ESL, cooking, or story video. It is preserved verbatim in
    tasks/engine-identity-seeds/power-doctrine.md.

    The "framework" here is just an optional angle hint passed downstream to the
    script/title stages (e.g. ``framework_angle or 'Not specified'``). The
    neutral script profile (neutral_v1) handles no-framework cleanly, so we no
    longer impose a theory. We return whatever niche-neutral angle the research
    actually surfaced — ``framework_analysis`` — or an empty string when there
    isn't one. Callers expect a string; an empty string is a valid value.

    Returns:
        A niche-neutral angle string drawn from the research, or "".
    """
    # The research stage's own framing of the topic — niche-agnostic by design
    # (a process, a cause-and-effect, a comparison, a story shape — whatever fit
    # the subject). No forced theory, no geopolitics default.
    angle = (payload.get("framework_analysis", "") or "").strip()
    return angle


def write_to_airtable(
    airtable_client,
    payload: dict,
    record_id: str = None,
    title_candidates: dict = None,
) -> dict:
    """Write a research payload to the Idea Concepts table.

    When record_id is provided, updates the existing record (e.g. after
    discovery → approval → research).  Otherwise creates a new record
    (standalone research run).

    Args:
        airtable_client: AirtableClient instance
        payload: Structured research_payload dict from ResearchAgent
        record_id: Optional existing Airtable record ID to update
        title_candidates: Optional title intelligence output from
                          generate_title_candidates()

    Returns:
        Airtable record dict with id
    """
    # Serialize full payload as JSON for the research_payload field
    research_payload_json = json.dumps(payload)

    # Validate payload size (Airtable long text limit ~100k chars)
    if len(research_payload_json) > 100000:
        logger.warning(
            f"Research payload is {len(research_payload_json)} chars — "
            f"may exceed Airtable field limit"
        )

    # Determine the best framework angle
    framework_angle = infer_framework_from_research(payload)
    logger.info(f"Inferred Framework Angle: {framework_angle}")

    # Use title intelligence winner if available, else fall back to headline
    video_title = payload.get("headline", "")
    if title_candidates and title_candidates.get("winner"):
        video_title = title_candidates["winner"]

    if record_id:
        # Update existing record — don't create a duplicate
        # Extract narrative fields from research payload
        narrative = extract_narrative_fields(payload)

        research_fields = {
            IdeaFields.RESEARCH_PAYLOAD: research_payload_json,
            IdeaFields.SOURCE_URLS: payload.get("source_bibliography", ""),
            IdeaFields.EXECUTIVE_HOOK: payload.get("executive_hook", ""),
            IdeaFields.THESIS: payload.get("thesis", ""),
            IdeaFields.FRAMEWORK_ANGLE: framework_angle,
            IdeaFields.THEMATIC_FRAMEWORK: payload.get("themes", ""),
            IdeaFields.HEADLINE: payload.get("headline", ""),
            # VIDEO_TITLE is deliberately NOT written on existing records: the
            # operator's chosen title is the product input (same decision that
            # disabled the post-script refiner - "user wants to keep their
            # chosen title"). Research silently renaming a video was seen live
            # on DvsU, where titles are the customer's proven series formats.
            # The scored candidates stay available in Title Candidates.
            # Narrative fields for Past → Present → Future framing
            IdeaFields.PAST_CONTEXT: narrative["past_context"],
            IdeaFields.PRESENT_PARALLEL: narrative["present_parallel"],
            IdeaFields.FUTURE_PREDICTION: narrative["future_prediction"],
        }
        # Add title candidates if generated
        if title_candidates and title_candidates.get("candidates"):
            research_fields["Title Candidates"] = json.dumps(
                title_candidates["candidates"]
            )
        if title_candidates and title_candidates.get("winner_thumbnail"):
            research_fields[IdeaFields.THUMBNAIL_TEXT] = title_candidates["winner_thumbnail"]

        airtable_client.update_idea_fields(record_id, research_fields)
        logger.info(f"Research updated on existing record: {record_id}")
        return {"id": record_id}

    # No record_id — create a brand-new record
    # Extract narrative fields from research payload
    narrative = extract_narrative_fields(payload)

    # Build the idea data dict compatible with AirtableClient.create_idea()
    idea_data = {
        "viral_title": video_title,
        "hook_script": payload.get("executive_hook", ""),
        "narrative_logic": narrative,  # Uses extract_narrative_fields for proper extraction
        "thumbnail_visual": (
            payload.get("thumbnail_concepts", "").split("\n")[0]
            if payload.get("thumbnail_concepts")
            else ""
        ),
        "writer_guidance": payload.get("_writer_guidance", ""),  # Cinematic direction, not thesis
        "original_dna": json.dumps({
            "source": "research_agent",
            "themes": payload.get("themes", ""),
            "psychological_angles": payload.get("psychological_angles", ""),
        }),
        # Rich schema fields
        IdeaFields.FRAMEWORK_ANGLE: framework_angle,
        IdeaFields.HEADLINE: payload.get("headline", ""),
        IdeaFields.EXECUTIVE_HOOK: payload.get("executive_hook", ""),
        IdeaFields.THESIS: payload.get("thesis", ""),
        IdeaFields.SOURCE_URLS: payload.get("source_bibliography", ""),
        IdeaFields.RESEARCH_PAYLOAD: research_payload_json,
        IdeaFields.THEMATIC_FRAMEWORK: payload.get("themes", ""),
    }

    # Add title candidates if generated
    if title_candidates and title_candidates.get("candidates"):
        idea_data["Title Candidates"] = json.dumps(title_candidates["candidates"])
    if title_candidates and title_candidates.get("winner_thumbnail"):
        idea_data[IdeaFields.THUMBNAIL_TEXT] = title_candidates["winner_thumbnail"]

    # Create the record with source="research_agent"
    record = airtable_client.create_idea(idea_data, source="research_agent")
    record_id = record["id"]

    logger.info(f"Research written to Idea Concepts: {record_id}")
    return record


async def run_research(
    anthropic_client,
    topic: str,
    seed_urls: Optional[list[str]] = None,
    context: Optional[str] = None,
    model: str = Models.CLAUDE_SONNET,
    airtable_client=None,
    record_id: str = None,
    system_prompt_override: Optional[str] = None,
) -> dict:
    """Convenience function to run deep research.

    This is the main entry point for external callers.

    Args:
        anthropic_client: AnthropicClient instance
        topic: Topic to research
        seed_urls: Optional seed URLs
        context: Optional context
        model: LLM model to use
        airtable_client: Optional AirtableClient — if provided, writes
                         research payload to Idea Concepts table
        record_id: Optional existing Airtable record ID to update
                   instead of creating a new record

    Returns:
        Structured research_payload dict (with airtable_record_id if written)
    """
    agent = ResearchAgent(
        anthropic_client,
        model=model,
        system_prompt_override=system_prompt_override,
    )
    payload = await agent.research(topic, seed_urls, context)

    # Phase 1: Generate title candidates using the formula library
    title_candidates = None
    try:
        framework = infer_framework_from_research(payload)
        topic_data = {
            "headline": payload.get("headline", ""),
            "entities": ", ".join(
                payload.get("character_dossier", "").split("\n")[:3]
            ),
            "hook": payload.get("executive_hook", ""),
            "thesis": payload.get("thesis", ""),
        }
        title_candidates = await generate_title_candidates(
            anthropic_client, topic_data, framework, model=model,
        )
        logger.info(
            f"Title intelligence: winner='{title_candidates.get('winner', '')}' "
            f"({len(title_candidates.get('candidates', []))} candidates)"
        )
    except Exception as e:
        # Non-blocking — title generation failure should NOT stop research
        logger.warning(f"Title candidate generation failed: {e}")

    # Phase 2: Enhance title with curiosity gap structure (if enabled)
    curiosity_data = None
    if CURIOSITY_GAP_ENABLED:
        try:
            engine = GapTitleEngine(anthropic_client)
            pattern_lib = PatternLibrary()

            # Build rich story context from research payload
            story_context = {
                "hook": payload.get("executive_hook", ""),
                "thesis": payload.get("thesis", ""),
                "facts": payload.get("fact_sheet", "")[:1000],  # Truncate for context
            }

            titles = await engine.generate_titles(
                story_context,
                pattern_library=pattern_lib,
                target_count=1,
            )

            if titles:
                best = titles[0]
                # Override title candidates winner with curiosity gap title
                if title_candidates:
                    title_candidates["winner"] = best.text
                    title_candidates["winner_thumbnail"] = best.thumbnail_text
                else:
                    title_candidates = {
                        "winner": best.text,
                        "winner_thumbnail": best.thumbnail_text,
                        "candidates": [],
                    }

                curiosity_data = {
                    "structure": best.structure.value,
                    "confidence": best.structure_confidence,
                    "thumbnail_text": best.thumbnail_text,
                    "thumbnail_approach": best.thumbnail_approach,
                }
                logger.info(
                    f"Curiosity gap: '{best.text}' "
                    f"({best.structure.value}, {best.structure_confidence}%)"
                )
        except Exception as e:
            # Non-blocking — keep original title on failure
            logger.warning(f"Curiosity gap enhancement failed: {e}")

    # Phase 3: Generate cinematic writer guidance from research payload
    # This creates scene-specific direction instead of just copying the thesis
    writer_guidance = ""
    try:
        writer_guidance = await _generate_cinematic_direction(anthropic_client, payload)
        if writer_guidance:
            logger.info("Generated cinematic writer guidance")
    except Exception as e:
        # Non-blocking — empty guidance is fine, script generator has its own rules
        logger.warning(f"Writer guidance generation failed: {e}")

    # Store in payload for write_to_airtable
    payload["_writer_guidance"] = writer_guidance

    # Write to Airtable if client provided
    if airtable_client is not None:
        record = write_to_airtable(
            airtable_client, payload,
            record_id=record_id,
            title_candidates=title_candidates,
        )
        payload["_airtable_record_id"] = record["id"]

        # Save curiosity structure metadata if generated
        if curiosity_data:
            try:
                airtable_client.update_idea_curiosity_structure(
                    record_id=record["id"],
                    structure=curiosity_data["structure"],
                    confidence=curiosity_data["confidence"],
                    thumbnail_text=curiosity_data["thumbnail_text"],
                    thumbnail_approach=curiosity_data["thumbnail_approach"],
                )
            except Exception as e:
                logger.warning(f"Could not save curiosity structure: {e}")

    # Attach title candidates to payload for callers
    if title_candidates:
        payload["_title_candidates"] = title_candidates

    # Attach curiosity data if generated
    if curiosity_data:
        payload["_curiosity_structure"] = curiosity_data

    return payload


# === CLI Entry Point ===

async def _cli_main():
    """CLI entry point for standalone research agent testing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="StoryEngine Deep Research Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python research_agent.py --topic "Why the US Dollar Could Collapse by 2030"
  python research_agent.py --topic "AI replacing jobs" --urls "https://example.com/report"
  python research_agent.py --topic "Federal Reserve rate cuts" --output research.json
""",
    )
    parser.add_argument(
        "--topic",
        required=True,
        help="The topic to research",
    )
    parser.add_argument(
        "--urls",
        nargs="*",
        help="Optional seed URLs for research",
    )
    parser.add_argument(
        "--context",
        help="Optional additional context",
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout as JSON)",
    )
    parser.add_argument(
        "--model",
        default=Models.CLAUDE_SONNET,
        help="Model to use (default: claude-sonnet-4-5-20250929)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save research payload to Airtable Idea Concepts table",
    )
    parser.add_argument(
        "--test-title",
        help="Test title generation only (skip full research). Provide a headline.",
    )

    args = parser.parse_args()

    # Load environment
    from dotenv import load_dotenv
    load_dotenv()

    from shared.clients.anthropic_client import AnthropicClient

    anthropic = AnthropicClient()

    # Title-only test mode
    if args.test_title:
        print(f"\n{'=' * 60}")
        print("TITLE INTELLIGENCE — Test Mode")
        print(f"{'=' * 60}")
        print(f"Headline: {args.test_title}")
        print(f"Model: {args.model}")
        print(f"{'=' * 60}\n")

        topic_data = {
            "headline": args.test_title,
            "entities": "",
            "hook": args.test_title,
            "thesis": args.test_title,
        }
        result = await generate_title_candidates(
            anthropic, topic_data, framework="", model=args.model,
        )
        print(json.dumps(result, indent=2))
        print(f"\n{'=' * 60}")
        print(f"Winner: {result.get('winner', 'N/A')}")
        print(f"Thumbnail: {result.get('winner_thumbnail', 'N/A')}")
        print(f"{'=' * 60}")
        return

    # Optionally initialize Airtable client
    airtable = None
    if args.save:
        from shared.clients.airtable_client import AirtableClient
        airtable = AirtableClient()

    print(f"\n{'=' * 60}")
    print(f"RESEARCH AGENT — Deep Research")
    print(f"{'=' * 60}")
    print(f"Topic: {args.topic}")
    if args.urls:
        print(f"Seed URLs: {args.urls}")
    print(f"Model: {args.model}")
    print(f"Save to Airtable: {'Yes' if args.save else 'No'}")
    print(f"{'=' * 60}\n")

    payload = await run_research(
        anthropic_client=anthropic,
        topic=args.topic,
        seed_urls=args.urls,
        context=args.context,
        model=args.model,
        airtable_client=airtable,
    )

    output_json = json.dumps(payload, indent=2)

    if args.output:
        Path(args.output).write_text(output_json)
        print(f"\n✅ Research saved to: {args.output}")
        print(f"   Headline: {payload.get('headline', 'N/A')}")
        print(f"   Fields: {len(payload)}")
    else:
        print(output_json)

    print(f"\n{'=' * 60}")
    print("Research complete.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(_cli_main())
