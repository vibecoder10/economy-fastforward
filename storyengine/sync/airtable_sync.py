"""
Airtable → Supabase sync bridge.

Syncs data from the existing Airtable pipeline into the Supabase PostgreSQL
database so the StoryEngine dashboard has real data to display.

Two modes:
    python airtable_sync.py --full    # Pull ALL records (backfill)
    python airtable_sync.py           # Pull records modified in last 5 min (cron)

Sync order: videos → scripts → assets → competitor_channels → competitor_videos
            → learnings → title_insights → title_tests

Cron (every 2 min):
    */2 * * * * cd /home/clawd/projects/storyengine && \
        /home/clawd/projects/storyengine/backend/venv/bin/python sync/airtable_sync.py \
        >> /tmp/storyengine-sync.log 2>&1
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment — load both .env files
# ---------------------------------------------------------------------------
# StoryEngine .env (Supabase creds)
_se_env = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_se_env)

# Pipeline .env (Airtable key lives here)
_pipeline_env = os.path.expanduser(
    "~/projects/economy-fastforward/.env"
)
if os.path.isfile(_pipeline_env):
    load_dotenv(_pipeline_env, override=False)  # don't clobber SE values

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")

# ---------------------------------------------------------------------------
# Airtable table IDs
# ---------------------------------------------------------------------------
IDEAS_TABLE = "tblrAsJglokZSkC8m"
SCRIPTS_TABLE = "tbluGSepeZNgb0NxG"
IMAGES_TABLE = "tbl3luJ0zsWu0MYYz"
COMPETITOR_CHANNELS_TABLE = "tblu9JgQ9LKI36iHC"
COMPETITOR_VIDEOS_TABLE = "tblSjIitAes9lq1WM"
OSIRIS_LEARNINGS_TABLE = "tblVH58hcdZLpacsn"
TITLE_INSIGHTS_TABLE = "tbl6nYxbY1A0MsUZc"
TITLE_TESTS_TABLE = "tbln8CPbNaMvERVn9"

# ---------------------------------------------------------------------------
# Status mapping — Airtable → dashboard
# ---------------------------------------------------------------------------
STATUS_MAP = {
    "Idea Logged": "idea_logged",
    "Ready for Scripting": "ready_for_scripting",
    "Scripting": "ready_for_scripting",
    "Ready for Voice": "ready_for_voice",
    "Voice Generation": "ready_for_voice",
    "Ready for Storyboards": "ready_for_storyboards",
    "Ready for Image Prompts": "ready_for_images",
    "Ready for Images": "ready_for_images",
    "Image Generation": "ready_for_images",
    "Ready for Thumbnail": "ready_for_thumbnail",
    "Ready to Render": "ready_to_render",
    "Rendering": "ready_to_render",
    "Rendered": "rendered",
    "Uploaded - Draft": "uploaded_draft",
    "Done": "done",
    "Published": "done",
}


def map_status(raw: str) -> str:
    """Convert Airtable Status to dashboard status key."""
    if raw in STATUS_MAP:
        return STATUS_MAP[raw]
    # Fallback: lowercase, spaces → underscores
    return raw.lower().replace(" ", "_").replace("-", "_")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _att_url(field_val: Any) -> Optional[str]:
    """Extract first attachment URL from an Airtable attachment field."""
    if isinstance(field_val, list) and field_val:
        return field_val[0].get("url")
    if isinstance(field_val, str) and field_val.startswith("http"):
        return field_val
    return None


def _parse_json(val: Any) -> Any:
    """Parse a JSON string; return dict/list or None."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val  # store as string if parse fails
    return None


def _int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _str(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, str):
        return val or None
    return str(val)


def _bool(val: Any) -> bool:
    """Convert Airtable checkbox to boolean."""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return bool(val)


def _json_str(val: Any) -> Optional[str]:
    """Parse JSON if string, then dump back. If parse fails, keep as string."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return json.dumps(parsed)
        except (json.JSONDecodeError, ValueError):
            return val
    return str(val)


# ---------------------------------------------------------------------------
# Airtable fetcher
# ---------------------------------------------------------------------------

def fetch_airtable_records(
    table_id: str,
    full_sync: bool = False,
) -> list[dict]:
    """Fetch records from an Airtable table.

    full_sync=False → only records modified in last 5 minutes.
    full_sync=True  → all records.
    """
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{table_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    params: dict[str, str] = {}

    if not full_sync:
        params["filterByFormula"] = (
            "DATETIME_DIFF(NOW(), LAST_MODIFIED_TIME(), 'minutes') < 5"
        )

    all_records: list[dict] = []
    with httpx.Client(timeout=60) as client:
        while True:
            resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            all_records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                break
            params["offset"] = offset

    return all_records


# ---------------------------------------------------------------------------
# Supabase client wrapper
# ---------------------------------------------------------------------------

class SupaSync:
    """Thin wrapper around supabase-py for sync operations."""

    def __init__(self):
        from supabase import create_client
        self.sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        self.tenant_id: Optional[str] = None

    def resolve_tenant(self) -> str:
        """Look up the 'eff' tenant UUID."""
        resp = (
            self.sb.table("tenants")
            .select("id")
            .eq("slug", "eff")
            .limit(1)
            .execute()
        )
        if not resp.data:
            raise RuntimeError(
                "No tenant with slug='eff'. Run schema.sql in Supabase first."
            )
        self.tenant_id = resp.data[0]["id"]
        return self.tenant_id

    # ---- video title → id cache -------------------------------------------
    _video_cache: dict[str, str] = {}

    def _rebuild_video_cache(self):
        """Rebuild the video title → UUID cache from DB."""
        self._video_cache.clear()
        resp = (
            self.sb.table("videos")
            .select("id, video_title")
            .eq("tenant_id", self.tenant_id)
            .execute()
        )
        for row in resp.data or []:
            if row.get("video_title"):
                self._video_cache[row["video_title"]] = row["id"]

    def _lookup_video_id(self, title: str) -> Optional[str]:
        """Find a video UUID by title (cached)."""
        if not title:
            return None
        if title in self._video_cache:
            return self._video_cache[title]
        resp = (
            self.sb.table("videos")
            .select("id")
            .eq("tenant_id", self.tenant_id)
            .eq("video_title", title)
            .limit(1)
            .execute()
        )
        if resp.data:
            vid = resp.data[0]["id"]
            self._video_cache[title] = vid
            return vid
        return None

    # ---- upsert helpers ---------------------------------------------------
    def _upsert(self, table: str, rows: list[dict], conflict_col: str = "airtable_record_id"):
        """Batch upsert rows, handling errors gracefully."""
        if not rows:
            return 0
        # supabase-py upsert in chunks of 500
        count = 0
        for i in range(0, len(rows), 500):
            chunk = rows[i : i + 500]
            try:
                self.sb.table(table).upsert(
                    chunk, on_conflict=conflict_col
                ).execute()
                count += len(chunk)
            except Exception as e:
                # Retry one-by-one for the failed chunk
                print(f"  Batch upsert failed on {table}, retrying individually: {e}")
                for row in chunk:
                    try:
                        self.sb.table(table).upsert(
                            row, on_conflict=conflict_col
                        ).execute()
                        count += 1
                    except Exception as e2:
                        _label = (
                            row.get("video_title")
                            or row.get("title")
                            or row.get("pattern")
                            or row.get("pattern_name")
                            or row.get("airtable_record_id", "?")
                        )
                        print(f"    Error upserting {table} row ({_label}): {e2}")
        return count

    # -----------------------------------------------------------------------
    # 1) VIDEOS — Idea Concepts → videos
    # -----------------------------------------------------------------------
    def sync_videos(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})

            # Parse JSON fields
            rp = _parse_json(f.get("Research Payload"))
            dna = _parse_json(f.get("Original DNA"))

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                # Core
                "video_title": _str(f.get("Video Title")),
                "status": map_status(f.get("Status", "Idea Logged")),
                "headline": _str(f.get("Headline")),
                "source": _str(f.get("Source")),
                # Editorial
                "framework_angle": _str(f.get("Framework Angle")),
                "thematic_framework": _str(f.get("Thematic Framework")),
                "hook_script": _str(f.get("Hook Script")),
                "past_context": _str(f.get("Past Context")),
                "present_parallel": _str(f.get("Present Parallel")),
                "future_prediction": _str(f.get("Future Prediction")),
                "writer_guidance": _str(f.get("Writer Guidance")),
                "thesis": _str(f.get("Thesis")),
                "executive_hook": _str(f.get("Executive Hook")),
                "script": _str(f.get("Script")),
                "seo_description": _str(f.get("SEO Description")),
                "seo_tags": _str(f.get("SEO Tags")),
                "seo_hashtags": _str(f.get("SEO Hashtags")),
                # Research
                "research_payload": json.dumps(rp) if isinstance(rp, (dict, list)) else rp,
                "original_dna": json.dumps(dna) if isinstance(dna, (dict, list)) else dna,
                "source_urls": _str(f.get("Source URLs")),
                "date_surfaced": _str(f.get("Date Surfaced")),
                # Scoring
                "timeliness_score": _float(f.get("Timeliness Score")),
                "audience_fit_score": _float(f.get("Audience Fit Score")),
                "content_gap_score": _float(f.get("Content Gap Score")),
                "structure_confidence": _float(f.get("Structure Confidence")),
                "curiosity_structure": _str(f.get("Curiosity Structure")),
                "monetization_risk": _str(f.get("Monetization Risk")),
                # Visual
                "thumbnail_prompt": _str(f.get("Thumbnail Prompt")),
                "thumbnail_style_override": _str(f.get("Thumbnail Style Override")),
                "thumbnail_text": _str(f.get("Thumbnail Text")),
                "thumbnail_approach": _str(f.get("Thumbnail Approach")),
                "accent_color": _str(f.get("Accent Color")) or "#00D4AA",
                "visual_style": _str(f.get("Visual Style")),
                "image_model": _str(f.get("Image Model")),
                "image_style_override": _str(f.get("Image Style Override")),
                "story_bible": _str(f.get("Story Bible")),
                "script_validation": _str(f.get("Script Validation")),
                "title_candidates": _str(f.get("Title Candidates")),
                "title_formula": _str(f.get("Title Formula")),
                "character_reference_url": _att_url(f.get("Character Reference")),
                "thumbnail_url": _att_url(f.get("Thumbnail")),
                # Video config
                "video_length_minutes": _float(f.get("Video Length (min)")),
                "clip_duration_seconds": _float(f.get("Clip Duration (s)")),
                # Drive / YouTube
                "final_video_url": _str(f.get("Final Video URL")),
                "drive_folder_link": _str(f.get("Drive Folder Link")),
                "drive_folder_id": _str(f.get("Drive Folder ID")),
                "youtube_video_id": _str(f.get("YouTube Video ID")),
                "youtube_url": _str(f.get("YouTube URL")),
                "upload_status": _str(f.get("Upload Status")),
                "upload_date": _str(f.get("Upload Date")),
                # Performance metrics
                "views": _int(f.get("Views")),
                "impressions": _int(f.get("Impressions")),
                "likes": _int(f.get("Likes")),
                "comments": _int(f.get("Comments")),
                "subscribers_gained": _int(f.get("Subscribers Gained")),
                "ctr": _float(f.get("CTR (%)")),
                "avg_view_duration_seconds": _float(f.get("Avg View Duration (s)")),
                "avg_retention": _float(f.get("Avg Retention (%)")),
                "watch_time_hours": _float(f.get("Watch Time (hours)")),
                "views_24h": _int(f.get("Views 24h")) if f.get("Views 24h") is not None else None,
                "views_48h": _int(f.get("Views 48h")) if f.get("Views 48h") is not None else None,
                "views_7d": _int(f.get("Views 7d")) if f.get("Views 7d") is not None else None,
                "views_30d": _int(f.get("Views 30d")) if f.get("Views 30d") is not None else None,
                "ctr_48h": _float(f.get("CTR 48h (%)")),
                "retention_48h": _float(f.get("Retention 48h (%)")),
                "last_analytics_sync": _str(f.get("Last Analytics Sync")),
                # Post-mortem
                "post_mortem_48h": _str(f.get("Post-Mortem 48h")),
                "post_mortem_7d": _str(f.get("Post-Mortem 7d")),
                "performance_verdict": _str(f.get("Performance Verdict")),
                # Timestamp
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            rows.append(row)

        count = self._upsert("videos", rows)
        # Rebuild the cache from DB after upsert
        self._rebuild_video_cache()
        return count

    # -----------------------------------------------------------------------
    # 2) SCRIPTS — Script table → scripts
    # -----------------------------------------------------------------------
    def sync_scripts(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})
            title = _str(f.get("Title")) or ""
            video_id = self._lookup_video_id(title) if title else None

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "video_id": video_id,
                # Fields
                "airtable_id": _float(f.get("ID")),
                "scene": _int(f.get("Scene")) if f.get("Scene") is not None else None,
                "title": title or None,
                "scene_text": _str(f.get("Scene text")),
                "script_status": _str(f.get("Script Status")),
                "voice_status": _str(f.get("Voice Status")),
                "voice_over_url": _att_url(f.get("Voice Over")),
                "voice_id": _str(f.get("Voice ID")),
                "sources": _str(f.get("Sources")),
                "framework": _str(f.get("Framework")),
                "psych_angle": _str(f.get("Psych Angle")),
                "sound_map": _str(f.get("Sound Map")),
                "sfx_status": _str(f.get("SFX Status")),
                "drive_folder": _str(f.get("Dive Folder")),
                "script_validation": _str(f.get("Script Validation")),
                "unverified_claims": _str(f.get("Unverified Claims")),
                # Storyboard
                "storyboard_on_off": _str(f.get("Story Board On/OFF")),
                "storyboard_prompts": _str(f.get("Storyboard Prompts")),
                "storyboard_beat_count": _float(f.get("Storyboard Beat Count")),
                "storyboard_status": _str(f.get("Storyboard Status")),
                "storyboard_1_url": _att_url(f.get("Storyboard 1")),
                "storyboard_2_url": _att_url(f.get("Storyboard 2")),
                "storyboard_3_url": _att_url(f.get("Storyboard 3")),
            }
            rows.append(row)

        return self._upsert("scripts", rows)

    # -----------------------------------------------------------------------
    # 3) ASSETS — Images table → assets
    # -----------------------------------------------------------------------
    def sync_assets(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})
            video_title = _str(f.get("Video Title")) or ""
            video_id = self._lookup_video_id(video_title) if video_title else None

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "video_id": video_id,
                "video_title": video_title or None,
                "scene": _int(f.get("Scene")) if f.get("Scene") is not None else None,
                "sentence_index": _int(f.get("Sentence Index")) if f.get("Sentence Index") is not None else None,
                "sentence_text": _str(f.get("Sentence Text")),
                "image_index": _int(f.get("Image Index")) if f.get("Image Index") is not None else None,
                "duration_seconds": _float(f.get("Duration (s)")),
                "image_prompt": _str(f.get("Image Prompt")),
                "shot_type": _str(f.get("Shot Type")),
                "image_url": _att_url(f.get("Image")),
                "status": _str(f.get("Status")),
                # Sound
                "sound_prompt": _str(f.get("Sound Prompt")),
                "sound_effect_url": _att_url(f.get("Sound Effect")),
                "sound_volume": _float(f.get("Sound Volume")),
                # Video/Animation
                "video_prompt": _str(f.get("Video Prompt")),
                "video_url": _att_url(f.get("Video")),
                "video_status": _str(f.get("Video Status")),
                "video_duration": _float(f.get("Video Duration")),
                "video_clip_url": _str(f.get("Video Clip URL")),
                "aspect_ratio": _str(f.get("Aspect Ratio")),
                "animation_status": _str(f.get("Animation Status")),
                "intensity": _str(f.get("Intensity")),
                "content_type": _str(f.get("Content Type")),
                # Flags
                "hero_shot": _bool(f.get("Hero Shot")),
            }
            rows.append(row)

        return self._upsert("assets", rows)

    # -----------------------------------------------------------------------
    # 4) COMPETITOR CHANNELS → competitor_channels
    # -----------------------------------------------------------------------
    def sync_competitor_channels(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "channel_url": _str(f.get("Channel URL")),
                "channel_name": _str(f.get("Channel Name")),
                "category": _str(f.get("Category")),
                "active": _bool(f.get("Active")),
                "last_scraped": _str(f.get("Last Scraped")),
                "notes": _str(f.get("Notes")),
            }
            rows.append(row)

        return self._upsert("competitor_channels", rows)

    # -----------------------------------------------------------------------
    # 5) COMPETITOR VIDEOS → competitor_videos
    # -----------------------------------------------------------------------
    def sync_competitor_videos(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "video_id": _str(f.get("Video ID")),
                "title": _str(f.get("Title")),
                "published_date": _str(f.get("Published Date")),
                "vph": _float(f.get("VPH")),
                "views": _int(f.get("Views")),
                "channel": _str(f.get("Channel")),
                "url": _str(f.get("URL")),
                "channel_url": _str(f.get("Channel URL")),
                "hours_old": _float(f.get("Hours Old")),
                "scrape_date": _str(f.get("Scrape Date")),
                "modeled": _bool(f.get("Modeled")),
                "our_video": _str(f.get("Our Video")),
                "topic_cluster": _str(f.get("Topic Cluster")),
                "curiosity_structure": _str(f.get("Curiosity Structure")),
                "structure_confidence": _float(f.get("Structure Confidence")),
                "thumbnail_style_json": _str(f.get("Thumbnail Style JSON")),
                "yin_yang_approach": _str(f.get("Yin Yang Approach")),
                "yin_yang_text": _str(f.get("Yin Yang Text")),
                "analysis_date": _str(f.get("Analysis Date")),
                "modeled_by_us": _bool(f.get("Modeled By Us")),
                "our_ctr_result": _float(f.get("Our CTR Result")),
            }
            rows.append(row)

        return self._upsert("competitor_videos", rows)

    # -----------------------------------------------------------------------
    # 6) LEARNINGS — Osiris Learnings → learnings
    # -----------------------------------------------------------------------
    def sync_learnings(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "pattern": _str(f.get("Pattern")),
                "category": _str(f.get("Category")),
                "detail": _str(f.get("Detail")),
                "confidence": _float(f.get("Confidence")),
                "sample_size": _float(f.get("Sample Size")),
                "avg_ctr": _float(f.get("Avg CTR")),
                "avg_retention": _float(f.get("Avg Retention")),
                "source_videos": _str(f.get("Source Videos")),
                "active": _bool(f.get("Active")),
                "created_date": _str(f.get("Created")),
                "last_updated": _str(f.get("Last Updated")),
            }
            rows.append(row)

        return self._upsert("learnings", rows)

    # -----------------------------------------------------------------------
    # 7) TITLE INSIGHTS → title_insights
    # -----------------------------------------------------------------------
    def sync_title_insights(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "name": _str(f.get("Name")),
                "pattern_name": _str(f.get("Pattern Name")),
                "description": _str(f.get("Description")),
                "example_titles": _str(f.get("Example Titles")),
                "analysis_date": _str(f.get("Analysis Date")),
                "pattern_type": _str(f.get("Pattern Type")),
                "avg_vph": _float(f.get("Avg VPH")),
                "count": _int(f.get("Count")) if f.get("Count") is not None else None,
                "confidence": _float(f.get("Confidence")),
                "videos_analyzed": _int(f.get("Videos Analyzed")) if f.get("Videos Analyzed") is not None else None,
                "vph_threshold": _float(f.get("VPH Threshold")),
            }
            rows.append(row)

        return self._upsert("title_insights", rows)

    # -----------------------------------------------------------------------
    # 8) TITLE TESTS → title_tests
    # -----------------------------------------------------------------------
    def sync_title_tests(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "idea": _str(f.get("Idea")),
                "title_text": _str(f.get("Title Text")),
                "structure": _str(f.get("Structure")),
                "structure_confidence": _float(f.get("Structure Confidence")),
                "thumbnail_text": _str(f.get("Thumbnail Text")),
                "thumbnail_approach": _str(f.get("Thumbnail Approach")),
                "source_patterns": _str(f.get("Source Patterns")),
                "pattern_library_snapshot": _str(f.get("Pattern Library Snapshot")),
                "poll_result": _str(f.get("Poll Result")),
                "poll_closed": _bool(f.get("Poll Closed")),
                "ctr_12h": _float(f.get("CTR 12h")),
                "ctr_24h": _float(f.get("CTR 24h")),
                "ctr_48h": _float(f.get("CTR 48h")),
                "selected": _bool(f.get("Selected")),
                "video_title": _str(f.get("Video Title")),
            }
            rows.append(row)

        return self._upsert("title_tests", rows)

    # -----------------------------------------------------------------------
    # Log sync activity
    # -----------------------------------------------------------------------
    def log_activity(self, message: str):
        try:
            self.sb.table("bot_activity").insert({
                "tenant_id": self.tenant_id,
                "bot_name": "airtable_sync",
                "status": "completed",
                "message": message,
            }).execute()
        except Exception as e:
            print(f"  Warning: could not log activity: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Airtable → Supabase sync")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full sync — pull ALL records (backfill). Default: last 5 minutes only.",
    )
    args = parser.parse_args()

    # Validate env
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_SERVICE_ROLE_KEY:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if not AIRTABLE_API_KEY:
        missing.append("AIRTABLE_API_KEY")
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}")
        print(f"  Checked: {_se_env}")
        print(f"  Checked: {_pipeline_env}")
        sys.exit(1)

    mode = "FULL" if args.full else "INCREMENTAL (last 5 min)"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{ts}] Airtable → Supabase sync — mode: {mode}")

    # Init Supabase client
    sync = SupaSync()
    tenant_id = sync.resolve_tenant()
    print(f"  Tenant: {tenant_id}")

    # ---- 1. Videos (Idea Concepts) ----------------------------------------
    print("  Fetching Idea Concepts...")
    try:
        idea_records = fetch_airtable_records(IDEAS_TABLE, full_sync=args.full)
    except Exception as e:
        print(f"  ERROR fetching ideas: {e}")
        idea_records = []
    print(f"    Found {len(idea_records)} records")
    video_count = sync.sync_videos(idea_records)
    print(f"    Synced {video_count} videos")

    # ---- 2. Scripts -------------------------------------------------------
    print("  Fetching Scripts...")
    try:
        script_records = fetch_airtable_records(SCRIPTS_TABLE, full_sync=args.full)
    except Exception as e:
        print(f"  ERROR fetching scripts: {e}")
        script_records = []
    print(f"    Found {len(script_records)} records")
    script_count = sync.sync_scripts(script_records)
    print(f"    Synced {script_count} scripts")

    # ---- 3. Images → assets -----------------------------------------------
    print("  Fetching Images...")
    try:
        image_records = fetch_airtable_records(IMAGES_TABLE, full_sync=args.full)
    except Exception as e:
        print(f"  ERROR fetching images: {e}")
        image_records = []
    print(f"    Found {len(image_records)} records")
    asset_count = sync.sync_assets(image_records)
    print(f"    Synced {asset_count} assets")

    # ---- 4. Competitor Channels -------------------------------------------
    print("  Fetching Competitor Channels...")
    try:
        channel_records = fetch_airtable_records(COMPETITOR_CHANNELS_TABLE, full_sync=args.full)
    except Exception as e:
        print(f"  ERROR fetching competitor channels: {e}")
        channel_records = []
    print(f"    Found {len(channel_records)} records")
    channel_count = sync.sync_competitor_channels(channel_records)
    print(f"    Synced {channel_count} channels")

    # ---- 5. Competitor Videos ---------------------------------------------
    print("  Fetching Competitor Videos...")
    try:
        comp_records = fetch_airtable_records(COMPETITOR_VIDEOS_TABLE, full_sync=args.full)
    except Exception as e:
        print(f"  ERROR fetching competitor videos: {e}")
        comp_records = []
    print(f"    Found {len(comp_records)} records")
    comp_count = sync.sync_competitor_videos(comp_records)
    print(f"    Synced {comp_count} competitor videos")

    # ---- 6. Osiris Learnings ----------------------------------------------
    print("  Fetching Osiris Learnings...")
    try:
        learning_records = fetch_airtable_records(OSIRIS_LEARNINGS_TABLE, full_sync=args.full)
    except Exception as e:
        print(f"  ERROR fetching learnings: {e}")
        learning_records = []
    print(f"    Found {len(learning_records)} records")
    learning_count = sync.sync_learnings(learning_records)
    print(f"    Synced {learning_count} learnings")

    # ---- 7. Title Insights ------------------------------------------------
    print("  Fetching Title Insights...")
    try:
        insight_records = fetch_airtable_records(TITLE_INSIGHTS_TABLE, full_sync=args.full)
    except Exception as e:
        print(f"  ERROR fetching title insights: {e}")
        insight_records = []
    print(f"    Found {len(insight_records)} records")
    insight_count = sync.sync_title_insights(insight_records)
    print(f"    Synced {insight_count} insights")

    # ---- 8. Title Tests ---------------------------------------------------
    print("  Fetching Title Tests...")
    try:
        test_records = fetch_airtable_records(TITLE_TESTS_TABLE, full_sync=args.full)
    except Exception as e:
        print(f"  ERROR fetching title tests: {e}")
        test_records = []
    print(f"    Found {len(test_records)} records")
    test_count = sync.sync_title_tests(test_records)
    print(f"    Synced {test_count} tests")

    # ---- Summary ----------------------------------------------------------
    summary = (
        f"Synced {video_count} videos, {script_count} scripts, "
        f"{asset_count} assets, {channel_count} channels, "
        f"{comp_count} competitor_videos, {learning_count} learnings, "
        f"{insight_count} insights, {test_count} tests"
    )
    sync.log_activity(summary)
    print(f"\n  {summary}")
    print("  Done!\n")


if __name__ == "__main__":
    main()
