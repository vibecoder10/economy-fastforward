"""
Airtable → Supabase sync bridge.

Syncs data from the existing Airtable pipeline into the Supabase PostgreSQL
database so the StoryEngine dashboard has real data to display.

Two modes:
    python airtable_sync.py --full    # Pull ALL records (backfill)
    python airtable_sync.py           # Pull records modified in last 5 min (cron)

Cron (every 2 min):
    */2 * * * * cd /home/clawd/projects/storyengine && \
        /home/clawd/projects/storyengine/backend/venv/bin/python sync/airtable_sync.py \
        >> /tmp/storyengine-sync.log 2>&1

Sync order: videos → scripts → images → competitor_videos → learnings
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
COMPETITOR_VIDEOS_TABLE = "tblSjIitAes9lq1WM"
OSIRIS_LEARNINGS_TABLE = "tblVH58hcdZLpacsn"

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
            return None
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

    def _lookup_video_id(self, title: str) -> Optional[str]:
        """Find a video UUID by title (cached)."""
        if title in self._video_cache:
            return self._video_cache[title]
        resp = (
            self.sb.table("videos")
            .select("id")
            .eq("tenant_id", self.tenant_id)
            .eq("title", title)
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
                        _label = row.get("title") or row.get("video_title") or row.get("pattern") or row.get("airtable_record_id", "?")
                        print(f"    Error upserting {table} row ({_label}): {e2}")
        return count

    # -----------------------------------------------------------------------
    # 1) VIDEOS — Idea Concepts → videos
    # -----------------------------------------------------------------------
    def sync_videos(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})
            title = f.get("Video Title") or f.get("Title") or "Untitled"
            rp = _parse_json(f.get("Research Payload"))
            dna = _parse_json(f.get("Original DNA"))

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "title": title,
                "status": map_status(f.get("Status", "Idea Logged")),
                "framework_angle": _str(f.get("Framework Angle")),
                "research_payload": json.dumps(rp) if rp else None,
                "original_dna": json.dumps(dna) if dna else None,
                "script": _str(f.get("Script")),
                "story_bible": _str(f.get("Story Bible")),
                "thumbnail_url": _att_url(f.get("Thumbnail")),
                "thumbnail_prompt": _str(f.get("Thumbnail Prompt")),
                "accent_color": _str(f.get("Accent Color")) or "#00D4AA",
                "visual_style": _str(f.get("Visual Style")) or "holographic_hud",
                "video_length_minutes": _int(f.get("Video Length (min)"), 10),
                "clip_duration_seconds": _int(f.get("Clip Duration (s)"), 10),
                "views": _int(f.get("Views")),
                "ctr": _float(f.get("CTR (%)")),
                "avg_retention": _float(f.get("Avg Retention (%)")),
                "youtube_url": _str(f.get("YouTube URL")),
                "total_cost": _float(f.get("Total Cost")) or 0,
                # Performance snapshots
                "post_mortem_48h": _str(f.get("Post-Mortem 48h")),
                "post_mortem_7d": _str(f.get("Post-Mortem 7d")),
                "performance_verdict": _str(f.get("Performance Verdict")),
                "upload_date": _str(f.get("Upload Date")),
                "views_24h": _int(f.get("Views 24h")) if f.get("Views 24h") is not None else None,
                "views_48h": _int(f.get("Views 48h")) if f.get("Views 48h") is not None else None,
                "views_7d": _int(f.get("Views 7d")) if f.get("Views 7d") is not None else None,
                "views_30d": _int(f.get("Views 30d")) if f.get("Views 30d") is not None else None,
                "ctr_48h": _float(f.get("CTR 48h (%)")),
                "retention_48h": _float(f.get("Retention 48h (%)")),
                "likes": _int(f.get("Likes")),
                "comments": _int(f.get("Comments")),
                "impressions": _int(f.get("Impressions")),
                "subscribers_gained": _int(f.get("Subscribers Gained")),
                "watch_time_hours": _float(f.get("Watch Time (hours)")),
                "avg_view_duration_seconds": (
                    _int(f.get("Avg View Duration (s)"))
                    if f.get("Avg View Duration (s)") is not None
                    else None
                ),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            rows.append(row)

            # Also seed the title→id cache once we know the record
            self._video_cache[title] = rec["id"]  # placeholder; real UUID comes from DB later

        count = self._upsert("videos", rows)
        # Rebuild the cache from DB after upsert
        self._video_cache.clear()
        return count

    # -----------------------------------------------------------------------
    # 2) SCRIPTS — Scripts table → scripts
    # -----------------------------------------------------------------------
    def sync_scripts(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})
            title = f.get("Title") or f.get("Video Title") or ""
            video_id = self._lookup_video_id(title)
            if not video_id:
                continue

            scene_text = _str(f.get("Scene text"))
            if not scene_text:
                continue

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "video_id": video_id,
                "scene_number": _int(f.get("Scene"), 1),
                "scene_text": scene_text,
                "voice_url": _att_url(f.get("Voice Over")),
                "voice_status": (
                    _str(f.get("Voice Status")) or "pending"
                ).lower(),
                "sources": _str(f.get("Sources")),
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
            title = f.get("Video Title") or f.get("Title") or ""
            video_id = self._lookup_video_id(title)
            if not video_id:
                continue

            url = _att_url(f.get("Image"))
            if not url:
                continue

            status_raw = (f.get("Status") or "Pending").strip()
            status = "done" if status_raw.lower() == "done" else "pending"

            metadata: dict[str, Any] = {}
            if f.get("Shot Type"):
                metadata["shot_type"] = f["Shot Type"]
            if f.get("Hero Shot"):
                metadata["hero_shot"] = f["Hero Shot"]
            if f.get("Video Clip URL"):
                metadata["video_clip_url"] = f["Video Clip URL"]
            if f.get("Sentence Text"):
                metadata["sentence_text"] = f["Sentence Text"]

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "video_id": video_id,
                "asset_type": "image",
                "scene_number": _int(f.get("Scene")) if f.get("Scene") is not None else None,
                "image_index": _int(f.get("Image Index")) if f.get("Image Index") is not None else None,
                "url": url,
                "prompt": _str(f.get("Image Prompt")),
                "status": status,
                "metadata": json.dumps(metadata) if metadata else None,
            }
            rows.append(row)

        return self._upsert("assets", rows)

    # -----------------------------------------------------------------------
    # 4) COMPETITOR VIDEOS
    # -----------------------------------------------------------------------
    def sync_competitor_videos(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})
            video_title = (
                f.get("Video Title") or f.get("Title") or f.get("video_title") or ""
            )
            if not video_title:
                continue

            # Thumbnail: could be attachment or plain URL
            thumb = _att_url(f.get("Thumbnail")) or _str(f.get("Thumbnail URL"))

            # Tags: could be string or list
            tags_raw = f.get("Tags")
            tags = None
            if isinstance(tags_raw, list):
                tags = json.dumps(tags_raw)
            elif isinstance(tags_raw, str):
                tags = json.dumps([t.strip() for t in tags_raw.split(",") if t.strip()])

            # Published date: many possible field names
            published = (
                _str(f.get("Published At"))
                or _str(f.get("Published"))
                or _str(f.get("Published Date"))
            )

            # Collect known fields, put the rest in metadata
            known_keys = {
                "Channel Name", "Channel", "Channel ID",
                "Video Title", "Title", "video_title",
                "Video URL", "URL", "Video ID",
                "Published At", "Published", "Published Date",
                "Views", "Likes", "Comments", "Duration",
                "Thumbnail", "Thumbnail URL", "Description", "Tags",
                "Category", "Topic", "Framework Match", "Relevance Score",
            }
            metadata = {k: v for k, v in f.items() if k not in known_keys}

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "channel_name": _str(f.get("Channel Name") or f.get("Channel")),
                "channel_id": _str(f.get("Channel ID")),
                "video_title": video_title,
                "video_url": _str(f.get("Video URL") or f.get("URL")),
                "video_id": _str(f.get("Video ID")),
                "published_at": published,
                "views": _int(f.get("Views")),
                "likes": _int(f.get("Likes")),
                "comments": _int(f.get("Comments")),
                "duration_seconds": _int(f.get("Duration")) if f.get("Duration") is not None else None,
                "thumbnail_url": thumb,
                "description": _str(f.get("Description")),
                "tags": tags,
                "category": _str(f.get("Category")),
                "topic": _str(f.get("Topic")),
                "framework_match": _str(f.get("Framework Match")),
                "relevance_score": _int(f.get("Relevance Score")) if f.get("Relevance Score") is not None else None,
                "metadata": json.dumps(metadata) if metadata else None,
            }
            rows.append(row)

        return self._upsert("competitor_videos", rows)

    # -----------------------------------------------------------------------
    # 5) LEARNINGS — Osiris Learnings → learnings
    # -----------------------------------------------------------------------
    def sync_learnings(self, records: list[dict]) -> int:
        rows: list[dict] = []
        for rec in records:
            f = rec.get("fields", {})
            pattern = _str(f.get("Pattern"))
            if not pattern:
                continue

            category_raw = (_str(f.get("Category")) or "").lower()
            valid_categories = {"title", "hook", "thumbnail", "retention", "framework"}
            category = category_raw if category_raw in valid_categories else None

            row = {
                "tenant_id": self.tenant_id,
                "airtable_record_id": rec["id"],
                "pattern": pattern,
                "category": category,
                "detail": _str(f.get("Detail")),
                "confidence": _int(f.get("Confidence")) if f.get("Confidence") is not None else None,
                "sample_size": _int(f.get("Sample Size")) if f.get("Sample Size") is not None else None,
                "avg_ctr": _float(f.get("Avg CTR")),
                "avg_retention": _float(f.get("Avg Retention")),
                "source_videos": _str(f.get("Source Videos")),
                "active": bool(f.get("Active", True)),
                "learned_at": _str(f.get("Created")),
                "last_updated": _str(f.get("Last Updated")),
            }
            rows.append(row)

        return self._upsert("learnings", rows)

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

    # ---- 4. Competitor Videos ---------------------------------------------
    print("  Fetching Competitor Videos...")
    try:
        comp_records = fetch_airtable_records(COMPETITOR_VIDEOS_TABLE, full_sync=args.full)
    except Exception as e:
        print(f"  ERROR fetching competitor videos: {e}")
        comp_records = []
    print(f"    Found {len(comp_records)} records")
    comp_count = sync.sync_competitor_videos(comp_records)
    print(f"    Synced {comp_count} competitor videos")

    # ---- 5. Osiris Learnings ----------------------------------------------
    print("  Fetching Osiris Learnings...")
    try:
        learning_records = fetch_airtable_records(OSIRIS_LEARNINGS_TABLE, full_sync=args.full)
    except Exception as e:
        print(f"  ERROR fetching learnings: {e}")
        learning_records = []
    print(f"    Found {len(learning_records)} records")
    learning_count = sync.sync_learnings(learning_records)
    print(f"    Synced {learning_count} learnings")

    # ---- Summary ----------------------------------------------------------
    summary = (
        f"Synced {video_count} videos, {script_count} scripts, "
        f"{asset_count} assets, {comp_count} competitor videos, "
        f"{learning_count} learnings"
    )
    sync.log_activity(summary)
    print(f"\n  {summary}")
    print("  Done!\n")


if __name__ == "__main__":
    main()
