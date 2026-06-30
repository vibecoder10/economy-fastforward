"""Learning Extraction API — Extract patterns from video performance data.

This is the WRITE side of the learning loop:
1. Videos get published → YouTube CTR/retention data arrives
2. This route detects title/hook/framework patterns in the video metadata
3. Patterns are tagged as KEEP (CTR >= 5%) or DISCARD (CTR <= 3%)
4. Stored in the `learnings` table in Supabase
5. Next time discovery generates ideas, it reads these patterns via _get_learnings_context()

The loop: Publish → Measure → Extract → Learn → Generate better titles → Publish
"""

import re
import json
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_all, fetch_one, execute

router = APIRouter(prefix="/api/learnings", tags=["learnings"])


# --- CTR Thresholds ---

CTR_STRONG = 5.0   # >= this = KEEP pattern
CTR_WEAK = 3.0     # <= this = DISCARD pattern


# --- Models ---

class ExtractedPattern(BaseModel):
    category: str       # title, hook, framework
    pattern: str        # e.g. "question_format", "counter_narrative"
    verdict: str        # KEEP, DISCARD, NEUTRAL
    confidence: int     # 60 (KEEP), 40 (DISCARD), 50 (NEUTRAL)
    avg_ctr: Optional[float] = None
    avg_retention: Optional[float] = None
    source_video: str


class ExtractionResult(BaseModel):
    videos_analyzed: int
    patterns_extracted: int
    patterns_new: int
    patterns_updated: int
    details: List[ExtractedPattern] = []


class LearningRecord(BaseModel):
    id: str
    category: str
    pattern: str
    confidence: float
    sample_size: int
    avg_ctr: Optional[float] = None
    avg_retention: Optional[float] = None
    source_videos: Optional[str] = None
    active: bool = True


# --- Pattern Detection ---

def _detect_title_patterns(title: str) -> list[str]:
    """Detect structural patterns in a video title."""
    patterns = []
    if not title:
        return patterns

    if title.rstrip().endswith("?"):
        patterns.append("question_format")
    if re.search(r'\$[\d,]+|\d+%|\d{4}', title):
        patterns.append("numbers_statistics")
    if re.search(r'20\d{2}', title):
        patterns.append("future_year")
    if re.search(r'\b[A-Z]{4,}\b', title):
        patterns.append("caps_emphasis")
    if ":" in title:
        patterns.append("colon_structure")
    if title.lower().startswith("how "):
        patterns.append("how_opener")
    elif title.lower().startswith("why "):
        patterns.append("why_opener")
    if any(w in title.lower() for w in ["secret", "quietly", "hidden", "actually"]):
        patterns.append("hidden_mechanism")
    if any(w in title.lower() for w in ["can't", "won't", "never", "impossible"]):
        patterns.append("impossibility_frame")
    if re.search(r"'s\s+\w+\s+(collapse|decline|crisis|trap|fall)", title.lower()):
        patterns.append("possessive_decline")

    return patterns


def _detect_hook_patterns(hook: str) -> list[str]:
    """Detect patterns in the video's opening hook."""
    patterns = []
    if not hook:
        return patterns

    if any(w in hook.lower() for w in ["but", "however", "actually", "truth"]):
        patterns.append("counter_narrative")
    if "?" in hook[:100]:
        patterns.append("question_opening")
    if re.search(r'\$[\d,]+|\d+%', hook[:150]):
        patterns.append("statistic_hook")
    if any(w in hook.lower() for w in ["imagine", "picture this", "what if"]):
        patterns.append("visualization_hook")

    return patterns


def _detect_script_patterns(script: str) -> list[str]:
    """Detect structural patterns in a full script/transcript."""
    patterns = []
    if not script:
        return patterns

    words = script.split()
    word_count = len(words)

    # Length pattern
    if word_count < 1500:
        patterns.append("short_form_script")
    elif word_count > 3500:
        patterns.append("long_form_script")
    else:
        patterns.append("medium_form_script")

    lower = script.lower()

    # Question density (high question density = engagement hooks throughout)
    question_count = script.count("?")
    if word_count > 0 and question_count / (word_count / 100) > 2:
        patterns.append("high_question_density")

    # Narrative structures
    if any(w in lower for w in ["years ago", "decades ago", "in the 19", "in the 20", "historically"]):
        patterns.append("historical_anchor")
    if any(w in lower for w in ["what happens next", "the future", "going forward", "will likely"]):
        patterns.append("future_projection")
    if re.search(r"(first|second|third|step \d|number \d)", lower):
        patterns.append("numbered_structure")
    if any(w in lower for w in ["the real question", "here's the thing", "the truth is", "what most people"]):
        patterns.append("insider_framing")
    if any(w in lower for w in ["billion", "million", "trillion", "percent"]):
        patterns.append("data_heavy")

    return patterns


def _detect_competitor_hook_patterns(transcript: str) -> list[str]:
    """Detect hook patterns from a competitor's transcript opening (first 500 words)."""
    if not transcript:
        return []

    # Only analyze the opening hook (first ~500 words)
    words = transcript.split()[:500]
    opening = " ".join(words)

    patterns = _detect_hook_patterns(opening)

    # Additional patterns specific to competitor transcripts
    lower = opening.lower()
    if any(w in lower for w in ["breaking", "just happened", "just announced", "right now"]):
        patterns.append("urgency_hook")
    if any(w in lower for w in ["story", "once", "there was", "back in"]):
        patterns.append("story_hook")
    if any(w in lower for w in ["nobody", "no one", "most people don't", "what they don't"]):
        patterns.append("exclusivity_hook")

    return patterns


def _get_verdict(ctr: float) -> tuple[str, int]:
    """Determine KEEP/DISCARD/NEUTRAL from CTR (the right signal for TITLES)."""
    if ctr >= CTR_STRONG:
        return "KEEP", 60
    elif ctr <= CTR_WEAK:
        return "DISCARD", 40
    else:
        return "NEUTRAL", 50


# Hooks and script structure live or die on RETENTION, not CTR (CTR is packaging).
# avg_retention is a percent (e.g. 35 = 35%).
RET_STRONG = 45.0  # >= this = the hook held viewers -> KEEP
RET_WEAK = 30.0    # <= this = viewers bailed early -> DISCARD


def _get_hook_verdict(ctr: float, retention: Optional[float]) -> tuple[str, int]:
    """Verdict for HOOK / SCRIPT / FRAMEWORK patterns. Judge on retention when we
    have it (a hook's real job is to hold the first 30s); fall back to CTR otherwise.
    This is what lets 'a video got bad retention' flip its hook to AVOID for next time."""
    if retention is not None:
        if retention >= RET_STRONG:
            return "KEEP", 65
        if retention <= RET_WEAK:
            return "DISCARD", 40
        return "NEUTRAL", 50
    return _get_verdict(ctr)


def _format_pattern_name(category: str, pattern: str) -> str:
    """Format pattern for human-readable display in learnings table."""
    labels = {
        "question_format": "Question format title",
        "numbers_statistics": "Numbers/statistics in title",
        "future_year": "Future year in title",
        "caps_emphasis": "ALL CAPS emphasis word",
        "colon_structure": "Colon structure (Topic: Hook)",
        "how_opener": "How opener",
        "why_opener": "Why opener",
        "hidden_mechanism": "Hidden mechanism language",
        "impossibility_frame": "Impossibility framing",
        "possessive_decline": "Possessive decline pattern",
        "counter_narrative": "Counter-narrative hook",
        "question_opening": "Question opening hook",
        "statistic_hook": "Statistic hook",
        "visualization_hook": "Visualization hook",
        # Script structure patterns
        "short_form_script": "Short-form script (<1500 words)",
        "medium_form_script": "Medium-form script (1500-3500 words)",
        "long_form_script": "Long-form script (>3500 words)",
        "high_question_density": "High question density throughout",
        "historical_anchor": "Historical anchor in narrative",
        "future_projection": "Future projection structure",
        "numbered_structure": "Numbered/sequential structure",
        "insider_framing": "Insider framing language",
        "data_heavy": "Data-heavy narrative",
        # Competitor hook patterns
        "urgency_hook": "Urgency/breaking news hook",
        "story_hook": "Story-based opening hook",
        "exclusivity_hook": "Exclusivity/secret knowledge hook",
    }
    return labels.get(pattern, pattern.replace("_", " ").title())


# --- Endpoints ---

@router.get("", response_model=List[LearningRecord])
async def get_learnings(
    category: Optional[str] = Query(None),
    active_only: bool = Query(True),
    limit: int = Query(20, le=50),
    tenant_id: str = Depends(get_tenant_id),
):
    """List all learnings from Supabase."""
    conditions = ["tenant_id = $1"]
    params: list = [tenant_id]
    idx = 2

    if active_only:
        conditions.append("active = true")

    if category:
        conditions.append(f"category = ${idx}")
        params.append(category)
        idx += 1

    where = " AND ".join(conditions)
    params.append(limit)

    rows = await fetch_all(
        f"""SELECT id, category, pattern, confidence, sample_size,
                   avg_ctr, avg_retention, source_videos, active
            FROM learnings
            WHERE {where}
            ORDER BY confidence DESC, avg_ctr DESC NULLS LAST
            LIMIT ${idx}""",
        *params,
    )

    return [
        LearningRecord(
            id=str(r["id"]),
            category=r.get("category", ""),
            pattern=r.get("pattern", ""),
            confidence=float(r.get("confidence", 0)),
            sample_size=int(r.get("sample_size", 0)),
            avg_ctr=float(r["avg_ctr"]) if r.get("avg_ctr") else None,
            avg_retention=float(r["avg_retention"]) if r.get("avg_retention") else None,
            source_videos=r.get("source_videos"),
            active=r.get("active", True),
        )
        for r in rows
    ]


@router.patch("/{learning_id}/toggle")
async def toggle_learning(
    learning_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Toggle a learning pattern's active status (true/false)."""
    row = await fetch_one(
        "SELECT id, active FROM learnings WHERE id = $1 AND tenant_id = $2",
        learning_id, tenant_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Learning not found")

    new_active = not row.get("active", True)
    await execute(
        "UPDATE learnings SET active = $1 WHERE id = $2",
        new_active, learning_id,
    )
    return {"id": learning_id, "active": new_active}


@router.post("/extract", response_model=ExtractionResult)
async def extract_learnings(
    tenant_id: str = Depends(get_tenant_id),
):
    """Extract title/hook/framework patterns from all videos with CTR data.

    Scans videos that have CTR data (impressions >= 1000) and haven't been
    analyzed yet. For each, detects patterns and saves to learnings table.
    """
    # Find videos with CTR data that haven't been analyzed yet
    videos = await fetch_all(
        """SELECT id, video_title, ctr, avg_retention, hook_script,
                  framework_angle, impressions, source, script
           FROM videos
           WHERE tenant_id = $1
             AND ctr IS NOT NULL
             AND COALESCE(impressions, 0) >= 1000
             AND learnings_extracted_at IS NULL
           ORDER BY ctr DESC""",
        tenant_id,
    )

    if not videos:
        return ExtractionResult(videos_analyzed=0, patterns_extracted=0,
                                 patterns_new=0, patterns_updated=0)

    # Get existing learnings to check for duplicates
    existing = await fetch_all(
        "SELECT category, pattern, source_videos FROM learnings WHERE tenant_id = $1",
        tenant_id,
    )
    existing_set = {(r.get("category", ""), r.get("pattern", "")) for r in existing}

    all_patterns: list[ExtractedPattern] = []
    new_count = 0
    updated_count = 0

    for video in videos:
        title = video.get("video_title", "")
        ctr = float(video.get("ctr", 0))
        retention = float(video["avg_retention"]) if video.get("avg_retention") else None
        hook = video.get("hook_script", "")
        framework = video.get("framework_angle", "")
        verdict, confidence = _get_verdict(ctr)          # CTR-based -> titles
        hv, hc = _get_hook_verdict(ctr, retention)        # retention-based -> hooks/script/framework

        # Skip only when NEITHER axis is decisive (a strong-CTR / weak-retention video
        # still teaches us about its hook, so don't drop it on the CTR axis alone).
        if verdict == "NEUTRAL" and hv == "NEUTRAL":
            continue

        # Detect title patterns (titles judged on CTR)
        for pattern in (_detect_title_patterns(title) if verdict != "NEUTRAL" else []):
            pattern_name = _format_pattern_name("title", pattern)
            ep = ExtractedPattern(
                category="title", pattern=pattern_name, verdict=verdict,
                confidence=confidence, avg_ctr=ctr, avg_retention=retention,
                source_video=title,
            )
            all_patterns.append(ep)

            result = await _upsert_learning(
                tenant_id, "title", pattern_name, ctr, retention, title,
                verdict, confidence, existing_set,
            )
            if result == "new":
                new_count += 1
            elif result == "updated":
                updated_count += 1

        # Detect hook patterns (hooks judged on RETENTION)
        for pattern in (_detect_hook_patterns(hook) if hv != "NEUTRAL" else []):
            pattern_name = _format_pattern_name("hook", pattern)
            ep = ExtractedPattern(
                category="hook", pattern=pattern_name, verdict=hv,
                confidence=hc, avg_ctr=ctr, avg_retention=retention,
                source_video=title,
            )
            all_patterns.append(ep)

            result = await _upsert_learning(
                tenant_id, "hook", pattern_name, ctr, retention, title,
                hv, hc, existing_set,
            )
            if result == "new":
                new_count += 1
            elif result == "updated":
                updated_count += 1

        # Extract framework pattern (structure -> judged on RETENTION)
        if framework and hv != "NEUTRAL":
            pattern_name = f"Framework: {framework}"
            ep = ExtractedPattern(
                category="framework", pattern=pattern_name, verdict=hv,
                confidence=hc, avg_ctr=ctr, avg_retention=retention,
                source_video=title,
            )
            all_patterns.append(ep)

            result = await _upsert_learning(
                tenant_id, "framework", pattern_name, ctr, retention, title,
                hv, hc, existing_set,
            )
            if result == "new":
                new_count += 1
            elif result == "updated":
                updated_count += 1

        # Detect script structure patterns (from full script text -> RETENTION)
        script_text = video.get("script", "")
        for pattern in (_detect_script_patterns(script_text) if hv != "NEUTRAL" else []):
            pattern_name = _format_pattern_name("script", pattern)
            ep = ExtractedPattern(
                category="script", pattern=pattern_name, verdict=hv,
                confidence=hc, avg_ctr=ctr, avg_retention=retention,
                source_video=title,
            )
            all_patterns.append(ep)

            result = await _upsert_learning(
                tenant_id, "script", pattern_name, ctr, retention, title,
                hv, hc, existing_set,
            )
            if result == "new":
                new_count += 1
            elif result == "updated":
                updated_count += 1

    # Mark all processed videos as extracted
    if videos:
        video_ids = [str(v["id"]) for v in videos]
        await execute(
            f"""UPDATE videos SET learnings_extracted_at = now()
                WHERE id = ANY($1::uuid[])""",
            video_ids,
        )

    return ExtractionResult(
        videos_analyzed=len(videos),
        patterns_extracted=len(all_patterns),
        patterns_new=new_count,
        patterns_updated=updated_count,
        details=all_patterns[:20],  # Cap details to avoid huge responses
    )


@router.post("/extract/{video_id}", response_model=ExtractionResult)
async def extract_learnings_for_video(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Extract patterns from a single video."""
    video = await fetch_one(
        """SELECT id, video_title, ctr, avg_retention, hook_script,
                  framework_angle, impressions
           FROM videos
           WHERE id = $1 AND tenant_id = $2""",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if video.get("ctr") is None:
        raise HTTPException(status_code=400, detail="Video has no CTR data yet")

    title = video.get("video_title", "")
    ctr = float(video.get("ctr", 0))
    retention = float(video["avg_retention"]) if video.get("avg_retention") else None
    hook = video.get("hook_script", "")
    framework = video.get("framework_angle", "")
    verdict, confidence = _get_verdict(ctr)

    existing = await fetch_all(
        "SELECT category, pattern, source_videos FROM learnings WHERE tenant_id = $1",
        tenant_id,
    )
    existing_set = {(r.get("category", ""), r.get("pattern", "")) for r in existing}

    all_patterns: list[ExtractedPattern] = []
    new_count = 0
    updated_count = 0

    for pattern in _detect_title_patterns(title):
        pattern_name = _format_pattern_name("title", pattern)
        all_patterns.append(ExtractedPattern(
            category="title", pattern=pattern_name, verdict=verdict,
            confidence=confidence, avg_ctr=ctr, avg_retention=retention,
            source_video=title,
        ))
        result = await _upsert_learning(
            tenant_id, "title", pattern_name, ctr, retention, title,
            verdict, confidence, existing_set,
        )
        if result == "new":
            new_count += 1
        elif result == "updated":
            updated_count += 1

    for pattern in _detect_hook_patterns(hook):
        pattern_name = _format_pattern_name("hook", pattern)
        all_patterns.append(ExtractedPattern(
            category="hook", pattern=pattern_name, verdict=verdict,
            confidence=confidence, avg_ctr=ctr, avg_retention=retention,
            source_video=title,
        ))
        result = await _upsert_learning(
            tenant_id, "hook", pattern_name, ctr, retention, title,
            verdict, confidence, existing_set,
        )
        if result == "new":
            new_count += 1
        elif result == "updated":
            updated_count += 1

    if framework:
        pattern_name = f"Framework: {framework}"
        all_patterns.append(ExtractedPattern(
            category="framework", pattern=pattern_name, verdict=verdict,
            confidence=confidence, avg_ctr=ctr, avg_retention=retention,
            source_video=title,
        ))
        result = await _upsert_learning(
            tenant_id, "framework", pattern_name, ctr, retention, title,
            verdict, confidence, existing_set,
        )
        if result == "new":
            new_count += 1
        elif result == "updated":
            updated_count += 1

    # Mark video as extracted
    await execute(
        "UPDATE videos SET learnings_extracted_at = now() WHERE id = $1",
        video_id,
    )

    return ExtractionResult(
        videos_analyzed=1,
        patterns_extracted=len(all_patterns),
        patterns_new=new_count,
        patterns_updated=updated_count,
        details=all_patterns,
    )


@router.post("/analyze-titles")
async def analyze_competitor_titles(
    tenant_id: str = Depends(get_tenant_id),
):
    """Analyze competitor video titles for structural patterns.

    Reads high-VPH competitor videos from Supabase, detects title patterns,
    and writes results to the title_insights table.
    """
    competitors = await fetch_all(
        """SELECT title, vph, channel
           FROM competitor_videos
           WHERE tenant_id = $1 AND vph >= 50
           ORDER BY vph DESC LIMIT 100""",
        tenant_id,
    )

    if not competitors:
        return {"status": "no_data", "message": "No competitor videos found"}

    # Aggregate patterns across all competitor titles
    pattern_stats: dict[str, dict] = {}

    for comp in competitors:
        title = comp.get("title", "")
        vph = float(comp.get("vph", 0))

        for pattern in _detect_title_patterns(title):
            if pattern not in pattern_stats:
                pattern_stats[pattern] = {
                    "count": 0, "total_vph": 0, "examples": [],
                }
            stats = pattern_stats[pattern]
            stats["count"] += 1
            stats["total_vph"] += vph
            if len(stats["examples"]) < 5:
                stats["examples"].append(title)

    # Write insights to Supabase
    from datetime import date
    today = date.today().isoformat()
    inserted = 0

    for pattern, stats in pattern_stats.items():
        if stats["count"] < 3:
            continue  # Need minimum sample

        avg_vph = stats["total_vph"] / stats["count"]
        confidence = min(95, 50 + stats["count"] * 2)  # More samples = more confident
        pattern_name = _format_pattern_name("title", pattern)

        try:
            await execute(
                """INSERT INTO title_insights (
                    tenant_id, analysis_date, pattern_type, pattern_name,
                    description, example_titles, avg_vph, count,
                    confidence, videos_analyzed, vph_threshold
                ) VALUES ($1, $2::date, 'structural', $3, $4, $5, $6, $7, $8, $9, 50)
                ON CONFLICT DO NOTHING""",
                tenant_id, today, pattern_name,
                f"Competitor titles using {pattern_name.lower()} pattern",
                json.dumps(stats["examples"]),
                avg_vph, stats["count"], confidence, len(competitors),
            )
            inserted += 1
        except Exception as e:
            print(f"[Learnings] Error inserting title insight: {e}")

    return {
        "status": "ok",
        "patterns_found": len(pattern_stats),
        "insights_saved": inserted,
        "videos_analyzed": len(competitors),
    }


@router.post("/analyze-transcripts")
async def analyze_competitor_transcripts(
    tenant_id: str = Depends(get_tenant_id),
):
    """Analyze competitor video transcripts for hook/structure patterns.

    Prefers distilled intelligence (content_intelligence table) over raw transcripts.
    Falls back to raw transcript analysis for un-distilled videos.
    Writes results to the title_insights table (as 'hook' type).
    """
    # First: use distilled hook data (no raw transcript needed — saves egress)
    distilled = await fetch_all(
        """SELECT cv.title, cv.vph, cv.channel,
                  ci.structured_metadata
           FROM content_intelligence ci
           JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
           WHERE ci.tenant_id = $1 AND ci.source_type = 'competitor_transcript'
             AND cv.vph >= 50
           ORDER BY cv.vph DESC LIMIT 50""",
        tenant_id,
    )

    # Fall back to raw transcripts for un-distilled videos
    raw_competitors = await fetch_all(
        """SELECT title, vph, channel, LEFT(transcript, 2000) as transcript
           FROM competitor_videos
           WHERE tenant_id = $1 AND vph >= 50
             AND distilled_at IS NULL
             AND transcript IS NOT NULL AND transcript != ''
           ORDER BY vph DESC LIMIT 50""",
        tenant_id,
    )

    if not distilled and not raw_competitors:
        return {"status": "no_data", "message": "No competitor videos with transcripts found"}

    total_analyzed = len(distilled or []) + len(raw_competitors or [])

    # Aggregate hook patterns across competitor transcripts
    pattern_stats: dict[str, dict] = {}

    # Process distilled intelligence first (already extracted hook types)
    import json
    for comp in (distilled or []):
        vph = float(comp.get("vph", 0))
        title = comp.get("title", "")
        metadata = comp.get("structured_metadata")
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if metadata:
            hook_type = (metadata.get("hook") or {}).get("type")
            if hook_type:
                pattern = f"hook_{hook_type}"
                if pattern not in pattern_stats:
                    pattern_stats[pattern] = {"count": 0, "total_vph": 0, "examples": []}
                stats = pattern_stats[pattern]
                stats["count"] += 1
                stats["total_vph"] += vph
                if len(stats["examples"]) < 5:
                    stats["examples"].append(title)

    # Process raw transcripts as fallback
    for comp in (raw_competitors or []):
        transcript = comp.get("transcript", "")
        vph = float(comp.get("vph", 0))
        title = comp.get("title", "")

        for pattern in _detect_competitor_hook_patterns(transcript):
            if pattern not in pattern_stats:
                pattern_stats[pattern] = {"count": 0, "total_vph": 0, "examples": []}
            stats = pattern_stats[pattern]
            stats["count"] += 1
            stats["total_vph"] += vph
            if len(stats["examples"]) < 5:
                stats["examples"].append(title)

    # Write insights to title_insights table (as 'hook' pattern type)
    from datetime import date
    today = date.today().isoformat()
    inserted = 0

    for pattern, stats in pattern_stats.items():
        if stats["count"] < 2:
            continue

        avg_vph = stats["total_vph"] / stats["count"]
        confidence = min(95, 50 + stats["count"] * 3)
        pattern_name = _format_pattern_name("hook", pattern)

        try:
            await execute(
                """INSERT INTO title_insights (
                    tenant_id, analysis_date, pattern_type, pattern_name,
                    description, example_titles, avg_vph, count,
                    confidence, videos_analyzed, vph_threshold
                ) VALUES ($1, $2::date, 'hook', $3, $4, $5, $6, $7, $8, $9, 50)
                ON CONFLICT DO NOTHING""",
                tenant_id, today, pattern_name,
                f"Competitor hook pattern: {pattern_name.lower()}",
                json.dumps(stats["examples"]),
                avg_vph, stats["count"], confidence, total_analyzed,
            )
            inserted += 1
        except Exception as e:
            print(f"[Learnings] Error inserting hook insight: {e}")

    return {
        "status": "ok",
        "patterns_found": len(pattern_stats),
        "insights_saved": inserted,
        "videos_analyzed": total_analyzed,
    }


# --- Internal Helpers ---

async def _upsert_learning(
    tenant_id: str,
    category: str,
    pattern: str,
    ctr: float,
    retention: Optional[float],
    video_title: str,
    verdict: str,
    confidence: int,
    existing_set: set,
) -> str:
    """Insert or update a learning pattern. Returns 'new', 'updated', or 'skipped'."""

    if (category, pattern) in existing_set:
        # Update existing: recalculate weighted average
        existing = await fetch_one(
            """SELECT id, avg_ctr, avg_retention, sample_size, source_videos, confidence
               FROM learnings
               WHERE tenant_id = $1 AND category = $2 AND pattern = $3""",
            tenant_id, category, pattern,
        )
        if not existing:
            return "skipped"

        old_ctr = float(existing.get("avg_ctr", 0) or 0)
        old_ret = float(existing.get("avg_retention", 0) or 0)
        old_n = int(existing.get("sample_size", 0) or 0)
        old_conf = float(existing.get("confidence", 50) or 50)

        # Check if this video already contributed
        source_str = existing.get("source_videos", "") or ""
        if video_title in source_str:
            return "skipped"

        new_n = old_n + 1
        new_ctr = (old_ctr * old_n + ctr) / new_n
        new_ret = ((old_ret * old_n + (retention or 0)) / new_n) if retention else old_ret

        # Confidence grows with consistent verdicts
        if verdict == "KEEP":
            new_conf = min(95, old_conf + 5)
        elif verdict == "DISCARD":
            new_conf = max(10, old_conf - 5)
        else:
            new_conf = old_conf

        # Append to source videos (keep last 10)
        sources = json.loads(source_str) if source_str.startswith("[") else [source_str] if source_str else []
        sources.append(video_title)
        sources = sources[-10:]

        await execute(
            """UPDATE learnings
               SET avg_ctr = $1, avg_retention = $2, sample_size = $3,
                   confidence = $4, source_videos = $5, last_updated = CURRENT_DATE
               WHERE id = $6""",
            round(new_ctr, 2), round(new_ret, 2), new_n,
            round(new_conf, 1), json.dumps(sources),
            str(existing["id"]),
        )
        return "updated"

    else:
        # Insert new learning
        sources = json.dumps([video_title])
        await execute(
            """INSERT INTO learnings (
                tenant_id, category, pattern, confidence, sample_size,
                avg_ctr, avg_retention, source_videos, active,
                created_date, last_updated
            ) VALUES ($1, $2, $3, $4, 1, $5, $6, $7, true, CURRENT_DATE, CURRENT_DATE)""",
            tenant_id, category, pattern, confidence,
            round(ctr, 2), round(retention, 2) if retention else None,
            sources,
        )
        existing_set.add((category, pattern))
        return "new"
