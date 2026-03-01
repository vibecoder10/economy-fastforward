"""Performance Analyzer — weekly actionable insights from YouTube data.

Runs weekly (Sunday 8 AM UTC) after performance_tracker.py has collected data.
Queries Airtable for all videos with YouTube analytics and produces prioritized
recommendations for title formulas, topics, velocity, and retention.

Prerequisites:
    - performance_tracker.py has been running daily (populates Views, CTR, Retention, etc.)
    - At least 8 videos with CTR data for meaningful analysis

Usage:
    python performance_analyzer.py              # Full analysis + Slack report
    python performance_analyzer.py --dry-run    # Print report without posting to Slack
    python performance_analyzer.py --json       # Output raw analysis as JSON

Cron (VPS):
    Sunday 8:00 AM UTC — after performance_tracker at 7:00 AM PT daily
    See setup_cron.sh for the full cron entry.

Also callable from Slack: "analyze" or "run analyze"
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load env from project root
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent))

from clients.airtable_client import AirtableClient

# Minimum videos with CTR data before analysis is meaningful
MIN_VIDEOS_FOR_ANALYSIS = 8


def _get_videos_with_analytics(airtable: AirtableClient) -> list[dict]:
    """Fetch all ideas that have YouTube analytics data.

    Returns records that have at least CTR or Retention populated.
    """
    all_ideas = airtable.get_all_ideas()
    return [
        idea for idea in all_ideas
        if idea.get("CTR (%)") is not None or idea.get("Avg Retention (%)") is not None
    ]


def _safe_float(value, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value, default: int = 0) -> int:
    """Safely convert a value to int."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def analyze_title_formulas(videos: list[dict]) -> dict:
    """Group videos by Title Formula and rank by CTR, retention, and 48h views.

    Returns:
        dict with "top", "bottom", and "all" formula rankings.
    """
    formula_groups: dict[str, list[dict]] = defaultdict(list)

    for v in videos:
        formula_id = v.get("Title Formula", "").strip()
        if not formula_id:
            continue
        formula_groups[formula_id].append(v)

    rankings = []
    for formula_id, group in formula_groups.items():
        ctrs = [_safe_float(v.get("CTR (%)")) for v in group if v.get("CTR (%)") is not None]
        retentions = [_safe_float(v.get("Avg Retention (%)")) for v in group if v.get("Avg Retention (%)") is not None]
        views_48h = [_safe_int(v.get("Views 48h")) for v in group if v.get("Views 48h") is not None]

        rankings.append({
            "formula_id": formula_id,
            "count": len(group),
            "avg_ctr": round(sum(ctrs) / len(ctrs), 2) if ctrs else 0.0,
            "avg_retention": round(sum(retentions) / len(retentions), 1) if retentions else 0.0,
            "avg_views_48h": round(sum(views_48h) / len(views_48h)) if views_48h else 0,
            "titles": [v.get("Video Title", "Unknown") for v in group],
        })

    rankings.sort(key=lambda r: r["avg_ctr"], reverse=True)

    top_3 = rankings[:3] if len(rankings) >= 3 else rankings
    bottom_3 = rankings[-3:] if len(rankings) >= 3 else []
    # Avoid overlap: remove any that appear in top_3
    bottom_3 = [r for r in bottom_3 if r not in top_3]

    insights = []
    for r in top_3:
        insights.append(
            f"DOUBLE DOWN: {r['formula_id']} averaging {r['avg_ctr']}% CTR "
            f"across {r['count']} video{'s' if r['count'] != 1 else ''}."
        )
    for r in bottom_3:
        insights.append(
            f"KILL: {r['formula_id']} averaging {r['avg_ctr']}% CTR "
            f"— stop using this title pattern."
        )

    return {"top": top_3, "bottom": bottom_3, "all": rankings, "insights": insights}


def analyze_topics(videos: list[dict]) -> dict:
    """Group videos by Thematic Framework / keywords and rank by impressions + CTR.

    Returns:
        dict with "categories" and "insights".
    """
    # Known topic categories to look for in titles and frameworks
    topic_keywords = {
        "sanctions": ["sanction", "embargo", "tariff", "trade war"],
        "currency": ["dollar", "currency", "yuan", "euro", "forex", "de-dollarization"],
        "military": ["military", "defense", "war", "weapon", "army", "navy", "missile", "nato"],
        "tech": ["tech", "ai", "chip", "semiconductor", "quantum", "cyber"],
        "cartels": ["cartel", "drug", "narco", "trafficking"],
        "energy": ["oil", "gas", "energy", "opec", "pipeline", "nuclear"],
        "geopolitics": ["geopolit", "alliance", "diplomacy", "conflict", "border"],
        "finance": ["bank", "debt", "inflation", "recession", "stock", "bond", "interest rate"],
    }

    category_data: dict[str, list[dict]] = defaultdict(list)

    for v in videos:
        title = (v.get("Video Title") or "").lower()
        framework = (v.get("Thematic Framework") or "").lower()
        combined = f"{title} {framework}"

        matched = False
        for category, keywords in topic_keywords.items():
            if any(kw in combined for kw in keywords):
                category_data[category].append(v)
                matched = True

        if not matched:
            category_data["other"].append(v)

    categories = []
    for category, group in category_data.items():
        impressions = [_safe_int(v.get("Impressions")) for v in group if v.get("Impressions") is not None]
        ctrs = [_safe_float(v.get("CTR (%)")) for v in group if v.get("CTR (%)") is not None]

        categories.append({
            "category": category,
            "count": len(group),
            "avg_impressions": round(sum(impressions) / len(impressions)) if impressions else 0,
            "total_impressions": sum(impressions),
            "avg_ctr": round(sum(ctrs) / len(ctrs), 2) if ctrs else 0.0,
            "titles": [v.get("Video Title", "Unknown") for v in group],
        })

    categories.sort(key=lambda c: c["total_impressions"], reverse=True)

    insights = []
    if len(categories) >= 2:
        best = categories[0]
        second = categories[1]
        if best["avg_impressions"] > 0 and second["avg_impressions"] > 0:
            ratio = round(best["avg_impressions"] / second["avg_impressions"], 1)
            insights.append(
                f"BEST TOPIC: {best['category'].title()} videos average "
                f"{ratio}x more impressions than {second['category'].title()} videos. "
                f"Prioritize {best['category']} angles."
            )

        # Find high-CTR niche categories
        high_ctr = [c for c in categories if c["avg_ctr"] >= 4.0 and c["count"] >= 2]
        for c in high_ctr[:2]:
            insights.append(
                f"HIGH CTR NICHE: {c['category'].title()} averages {c['avg_ctr']}% CTR "
                f"across {c['count']} videos."
            )

    return {"categories": categories, "insights": insights}


def analyze_velocity(videos: list[dict]) -> dict:
    """Analyze initial velocity (24h/48h/7d views) and diagnose impression vs CTR problems.

    Returns:
        dict with "high_velocity", "low_ctr_high_impressions", "low_impressions", "insights".
    """
    velocity_data = []
    high_impressions_low_ctr = []
    low_impressions = []

    for v in videos:
        title = v.get("Video Title", "Unknown")
        views_24h = _safe_int(v.get("Views 24h"))
        views_48h = _safe_int(v.get("Views 48h"))
        views_7d = _safe_int(v.get("Views 7d"))
        impressions = _safe_int(v.get("Impressions"))
        ctr = _safe_float(v.get("CTR (%)"))

        # Velocity: ratio of 48h views to 7d views (high = fast initial pickup)
        if views_48h > 0 and views_7d > 0:
            velocity_ratio = round(views_48h / views_7d, 2)
            velocity_data.append({
                "title": title,
                "views_24h": views_24h,
                "views_48h": views_48h,
                "views_7d": views_7d,
                "velocity_ratio": velocity_ratio,
            })

        # Diagnose: high impressions but low CTR = thumbnail/title problem
        if impressions > 1000 and ctr > 0 and ctr < 3.0:
            high_impressions_low_ctr.append({
                "title": title,
                "impressions": impressions,
                "ctr": ctr,
            })

        # Diagnose: low impressions = topic/timing problem
        if impressions is not None and v.get("Impressions") is not None and impressions < 500:
            low_impressions.append({
                "title": title,
                "impressions": impressions,
            })

    velocity_data.sort(key=lambda d: d["velocity_ratio"], reverse=True)

    insights = []
    for item in high_impressions_low_ctr:
        insights.append(
            f"HIGH IMPRESSIONS LOW CTR: '{item['title']}' got "
            f"{item['impressions']:,} impressions but {item['ctr']}% CTR "
            f"— thumbnail or title needs work."
        )
    for item in low_impressions:
        insights.append(
            f"LOW IMPRESSIONS: '{item['title']}' got {item['impressions']:,} "
            f"impressions — topic has no search demand."
        )
    if velocity_data:
        best = velocity_data[0]
        insights.insert(0,
            f"FASTEST PICKUP: '{best['title']}' — "
            f"{best['views_48h']:,} views in 48h "
            f"({best['velocity_ratio']:.0%} of 7d total)."
        )

    return {
        "high_velocity": velocity_data[:5],
        "low_ctr_high_impressions": high_impressions_low_ctr,
        "low_impressions": low_impressions,
        "insights": insights,
    }


def analyze_retention(videos: list[dict]) -> dict:
    """Rank videos by retention and cross-reference with scene count.

    Returns:
        dict with "rankings", "scene_count_correlation", "insights".
    """
    retention_data = []

    for v in videos:
        retention = v.get("Avg Retention (%)")
        if retention is None:
            continue
        retention_data.append({
            "title": v.get("Video Title", "Unknown"),
            "retention": _safe_float(retention),
            "scene_count": _safe_int(v.get("Scene Count")),
            "framework": v.get("Thematic Framework", ""),
        })

    retention_data.sort(key=lambda d: d["retention"], reverse=True)

    # Cross-reference scene count with retention
    scene_buckets: dict[str, list[float]] = defaultdict(list)
    for d in retention_data:
        sc = d["scene_count"]
        if sc == 0:
            continue
        if sc <= 17:
            bucket = "<=17"
        elif sc <= 22:
            bucket = "18-22"
        else:
            bucket = "23+"
        scene_buckets[bucket].append(d["retention"])

    scene_correlation = {}
    for bucket, retentions in scene_buckets.items():
        scene_correlation[bucket] = {
            "avg_retention": round(sum(retentions) / len(retentions), 1),
            "count": len(retentions),
        }

    insights = []
    if retention_data:
        best = retention_data[0]
        insights.append(
            f"BEST RETENTION: '{best['title']}' at {best['retention']}%."
        )
        if len(retention_data) >= 3:
            worst = retention_data[-1]
            insights.append(
                f"WORST RETENTION: '{worst['title']}' at {worst['retention']}%."
            )

    # Scene count insight
    if len(scene_correlation) >= 2:
        sorted_buckets = sorted(
            scene_correlation.items(),
            key=lambda x: x[1]["avg_retention"],
            reverse=True,
        )
        best_bucket = sorted_buckets[0]
        worst_bucket = sorted_buckets[-1]
        if best_bucket[1]["avg_retention"] > worst_bucket[1]["avg_retention"]:
            insights.append(
                f"SCENE COUNT: Videos with {best_bucket[0]} scenes average "
                f"{best_bucket[1]['avg_retention']}% retention vs "
                f"{worst_bucket[1]['avg_retention']}% for {worst_bucket[0]} scene videos."
            )

    return {
        "rankings": retention_data[:10],
        "scene_count_correlation": scene_correlation,
        "insights": insights,
    }


def generate_recommendations(
    formula_analysis: dict,
    topic_analysis: dict,
    velocity_analysis: dict,
    retention_analysis: dict,
) -> list[str]:
    """Combine all analyses into max 5 prioritized recommendations.

    Each recommendation has a specific next step.
    """
    candidates = []

    # 1. Best title formulas
    if formula_analysis["top"]:
        top_formulas = [r["formula_id"] for r in formula_analysis["top"][:2]]
        candidates.append((
            formula_analysis["top"][0]["avg_ctr"],
            f"USE {' or '.join(top_formulas)} for next 3 videos "
            f"(highest CTR at {formula_analysis['top'][0]['avg_ctr']}%)."
        ))

    # 2. Best topic to cover
    if topic_analysis["categories"]:
        best_topic = topic_analysis["categories"][0]
        candidates.append((
            best_topic["total_impressions"],
            f"Make a video about {best_topic['category']} "
            f"— highest impression category "
            f"({best_topic['avg_impressions']:,} avg impressions)."
        ))

    # 3. Scene count optimization
    scene_corr = retention_analysis.get("scene_count_correlation", {})
    if scene_corr:
        best_bucket = max(scene_corr.items(), key=lambda x: x[1]["avg_retention"])
        if best_bucket[1]["count"] >= 2:
            candidates.append((
                best_bucket[1]["avg_retention"],
                f"Target {best_bucket[0]} scenes per script "
                f"— best retention at {best_bucket[1]['avg_retention']}%."
            ))

    # 4. Kill bad formulas
    if formula_analysis["bottom"]:
        worst = formula_analysis["bottom"][-1]
        candidates.append((
            100 - worst["avg_ctr"],  # Invert so low CTR = high priority
            f"Stop using {worst['formula_id']} titles "
            f"— consistently lowest CTR at {worst['avg_ctr']}%."
        ))

    # 5. Fix thumbnail/title problems
    low_ctr_list = velocity_analysis.get("low_ctr_high_impressions", [])
    if low_ctr_list:
        worst_ctr = min(low_ctr_list, key=lambda x: x["ctr"])
        candidates.append((
            100 - worst_ctr["ctr"],
            f"Re-test thumbnail for '{worst_ctr['title']}' "
            f"— {worst_ctr['impressions']:,} impressions but only {worst_ctr['ctr']}% CTR."
        ))

    # Sort by priority score descending, take top 5
    candidates.sort(key=lambda c: c[0], reverse=True)
    return [f"{i+1}. {text}" for i, (_, text) in enumerate(candidates[:5])]


def build_slack_report(
    formula_analysis: dict,
    topic_analysis: dict,
    velocity_analysis: dict,
    retention_analysis: dict,
    recommendations: list[str],
    video_count: int,
) -> str:
    """Format all analyses into a clean Slack message with data tables."""
    lines = [
        "*Weekly Performance Analysis*",
        f"_Based on {video_count} videos with analytics data_\n",
    ]

    # --- Title Formulas ---
    lines.append("*Title Formula Rankings*")
    for r in formula_analysis["all"][:8]:
        lines.append(
            f"  {r['formula_id']}: {r['avg_ctr']}% CTR | "
            f"{r['avg_retention']}% retention | "
            f"{r['count']} video{'s' if r['count'] != 1 else ''}"
        )
    lines.append("")

    # --- Topic Performance ---
    lines.append("*Topic Performance*")
    for c in topic_analysis["categories"][:6]:
        if c["count"] == 0:
            continue
        lines.append(
            f"  {c['category'].title()}: {c['avg_impressions']:,} avg impressions | "
            f"{c['avg_ctr']}% CTR | {c['count']} video{'s' if c['count'] != 1 else ''}"
        )
    lines.append("")

    # --- Velocity Alerts ---
    alerts = velocity_analysis.get("low_ctr_high_impressions", [])
    low_imp = velocity_analysis.get("low_impressions", [])
    if alerts or low_imp:
        lines.append("*Alerts*")
        for a in alerts[:3]:
            lines.append(
                f"  :warning: '{a['title']}' — {a['impressions']:,} impressions, "
                f"{a['ctr']}% CTR (thumbnail/title problem)"
            )
        for li in low_imp[:3]:
            lines.append(
                f"  :small_red_triangle_down: '{li['title']}' — "
                f"{li['impressions']:,} impressions (low demand)"
            )
        lines.append("")

    # --- Retention ---
    lines.append("*Retention Leaders*")
    for r in retention_analysis["rankings"][:5]:
        sc = f" ({r['scene_count']} scenes)" if r["scene_count"] else ""
        lines.append(f"  {r['title']}: {r['retention']}%{sc}")
    scene_corr = retention_analysis.get("scene_count_correlation", {})
    if scene_corr:
        parts = [f"{bucket}: {data['avg_retention']}%" for bucket, data in sorted(scene_corr.items())]
        lines.append(f"  Scene count vs retention: {' | '.join(parts)}")
    lines.append("")

    # --- Recommendations ---
    lines.append("*Recommendations*")
    for rec in recommendations:
        lines.append(f"  {rec}")

    return "\n".join(lines)


def run_analysis(dry_run: bool = False, output_json: bool = False) -> str | None:
    """Run the full performance analysis pipeline.

    Args:
        dry_run: Print report to stdout without posting to Slack.
        output_json: Output raw analysis dict as JSON instead of Slack format.

    Returns:
        The Slack report string, or None if not enough data.
    """
    airtable = AirtableClient()
    videos = _get_videos_with_analytics(airtable)

    videos_with_ctr = [v for v in videos if v.get("CTR (%)") is not None]

    if len(videos_with_ctr) < MIN_VIDEOS_FOR_ANALYSIS:
        needed = MIN_VIDEOS_FOR_ANALYSIS - len(videos_with_ctr)
        msg = (
            f"*Performance Analysis*\n"
            f"Not enough data yet — need {needed} more video{'s' if needed != 1 else ''} "
            f"with analytics. Currently have {len(videos_with_ctr)}/{MIN_VIDEOS_FOR_ANALYSIS}."
        )
        print(msg)
        if not dry_run:
            try:
                from clients.slack_client import SlackClient
                SlackClient().notify(msg)
            except Exception as e:
                print(f"Slack notification failed (non-blocking): {e}")
        return msg

    print(f"Analyzing {len(videos)} videos ({len(videos_with_ctr)} with CTR data)...\n")

    formula_analysis = analyze_title_formulas(videos)
    topic_analysis = analyze_topics(videos)
    velocity_analysis = analyze_velocity(videos)
    retention_analysis = analyze_retention(videos)
    recommendations = generate_recommendations(
        formula_analysis, topic_analysis, velocity_analysis, retention_analysis,
    )

    if output_json:
        result = {
            "video_count": len(videos),
            "videos_with_ctr": len(videos_with_ctr),
            "formulas": formula_analysis,
            "topics": topic_analysis,
            "velocity": velocity_analysis,
            "retention": retention_analysis,
            "recommendations": recommendations,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(result, indent=2, default=str))
        return None

    report = build_slack_report(
        formula_analysis,
        topic_analysis,
        velocity_analysis,
        retention_analysis,
        recommendations,
        len(videos),
    )

    print(report)

    if not dry_run:
        try:
            from clients.slack_client import SlackClient
            SlackClient().send_message(report)
            print("\nSlack report sent.")
        except Exception as e:
            print(f"\nSlack notification failed (non-blocking): {e}")

    return report


if __name__ == "__main__":
    is_dry_run = "--dry-run" in sys.argv
    is_json = "--json" in sys.argv
    run_analysis(dry_run=is_dry_run, output_json=is_json)
