"""
Airtable → Supabase sync bridge.

Runs every 2 minutes via cron. Reads from the existing Airtable base
and upserts into Supabase PostgreSQL. The existing pipeline keeps writing
to Airtable — this dashboard reads from Supabase.

Usage:
    python sync/airtable_sync.py

Cron:
    */2 * * * * cd ~/projects/storyengine && python sync/airtable_sync.py >> /tmp/storyengine-sync.log 2>&1
"""

import os
import sys
import json
import asyncio
import asyncpg
from datetime import datetime, timezone, timedelta
from typing import Optional
from dotenv import load_dotenv

# Load env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Optional: use the existing pipeline's airtable client
PIPELINE_PATH = os.path.expanduser("~/projects/economy-fastforward/skills/video-pipeline")
if os.path.isdir(PIPELINE_PATH):
    sys.path.insert(0, PIPELINE_PATH)

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

# Config
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")
DATABASE_URL = os.getenv("DATABASE_URL")

# Table IDs
IDEAS_TABLE = "tblrAsJglokZSkC8m"
SCRIPTS_TABLE = "tbluGSepeZNgb0NxG"
IMAGES_TABLE = "tbl3luJ0zsWu0MYYz"

# Ryan's tenant ID — hardcoded for now
TENANT_ID: Optional[str] = None  # Will be fetched from DB

# Airtable status → dashboard status mapping
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


def map_status(airtable_status: str) -> str:
    """Map Airtable status to dashboard status."""
    return STATUS_MAP.get(airtable_status, "idea_logged")


async def fetch_airtable_records(table_id: str, filter_formula: Optional[str] = None) -> list:
    """Fetch records from Airtable."""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{table_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    params = {}
    if filter_formula:
        params["filterByFormula"] = filter_formula

    all_records = []
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            all_records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                break
            params["offset"] = offset

    return all_records


async def sync_videos(pool: asyncpg.Pool, tenant_id: str):
    """Sync Idea Concepts table → videos table."""
    # Fetch recently modified records (last 10 minutes to catch any missed)
    filter_formula = "DATETIME_DIFF(NOW(), LAST_MODIFIED_TIME(), 'minutes') < 10"
    try:
        records = await fetch_airtable_records(IDEAS_TABLE, filter_formula)
    except Exception as e:
        print(f"  Error fetching ideas: {e}")
        # Fallback: fetch all records
        records = await fetch_airtable_records(IDEAS_TABLE)

    print(f"  Found {len(records)} idea records to sync")

    async with pool.acquire() as conn:
        for record in records:
            fields = record.get("fields", {})
            airtable_id = record["id"]
            title = fields.get("Video Title", fields.get("Title", "Untitled"))
            status = map_status(fields.get("Status", "Idea Logged"))

            # Extract performance data
            views = fields.get("Views", 0) or 0
            ctr = fields.get("CTR (%)", None)
            avg_retention = fields.get("Avg Retention (%)", None)
            youtube_url = fields.get("YouTube URL", None)
            total_cost = fields.get("Total Cost", 0) or 0

            # Extract other fields
            script = fields.get("Script", None)
            framework_angle = fields.get("Framework Angle", None)
            visual_style = fields.get("Visual Style", "holographic_hud")
            accent_color = fields.get("Accent Color", "#00D4AA")
            thumbnail_prompt = fields.get("Thumbnail Prompt", None)
            video_length = fields.get("Video Length (min)", 10) or 10
            story_bible = fields.get("Story Bible", None)

            # Thumbnail URL from attachment
            thumbnail_url = None
            thumbnail_field = fields.get("Thumbnail")
            if thumbnail_field and isinstance(thumbnail_field, list) and len(thumbnail_field) > 0:
                thumbnail_url = thumbnail_field[0].get("url")

            # Research payload
            research_payload = None
            rp = fields.get("Research Payload")
            if rp:
                try:
                    research_payload = json.loads(rp) if isinstance(rp, str) else rp
                except json.JSONDecodeError:
                    pass

            try:
                await conn.execute(
                    """INSERT INTO videos (
                        tenant_id, airtable_record_id, title, status,
                        framework_angle, research_payload, script, story_bible,
                        thumbnail_url, thumbnail_prompt, accent_color, visual_style,
                        video_length_minutes, views, ctr, avg_retention, youtube_url,
                        total_cost, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, now())
                    ON CONFLICT (airtable_record_id) WHERE airtable_record_id IS NOT NULL
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        status = EXCLUDED.status,
                        framework_angle = EXCLUDED.framework_angle,
                        research_payload = EXCLUDED.research_payload,
                        script = EXCLUDED.script,
                        story_bible = EXCLUDED.story_bible,
                        thumbnail_url = EXCLUDED.thumbnail_url,
                        thumbnail_prompt = EXCLUDED.thumbnail_prompt,
                        accent_color = EXCLUDED.accent_color,
                        visual_style = EXCLUDED.visual_style,
                        video_length_minutes = EXCLUDED.video_length_minutes,
                        views = EXCLUDED.views,
                        ctr = EXCLUDED.ctr,
                        avg_retention = EXCLUDED.avg_retention,
                        youtube_url = EXCLUDED.youtube_url,
                        total_cost = EXCLUDED.total_cost,
                        updated_at = now()""",
                    tenant_id, airtable_id, title, status,
                    framework_angle, json.dumps(research_payload) if research_payload else None,
                    script, story_bible,
                    thumbnail_url, thumbnail_prompt, accent_color, visual_style,
                    video_length, views, ctr, avg_retention, youtube_url,
                    total_cost,
                )
            except Exception as e:
                print(f"  Error upserting video {title[:30]}: {e}")

    return len(records)


async def sync_assets(pool: asyncpg.Pool, tenant_id: str):
    """Sync Images table → assets table."""
    filter_formula = "DATETIME_DIFF(NOW(), LAST_MODIFIED_TIME(), 'minutes') < 10"
    try:
        records = await fetch_airtable_records(IMAGES_TABLE, filter_formula)
    except Exception:
        records = await fetch_airtable_records(IMAGES_TABLE)

    print(f"  Found {len(records)} image records to sync")

    async with pool.acquire() as conn:
        for record in records:
            fields = record.get("fields", {})
            video_title = fields.get("Video Title", "")
            scene_number = fields.get("Scene", None)
            image_index = fields.get("Image Index", None)
            prompt = fields.get("Image Prompt", None)
            status_raw = fields.get("Status", "Pending")
            status = "done" if status_raw == "Done" else "pending"

            # Get image URL from attachment
            url = None
            image_field = fields.get("Image")
            if image_field and isinstance(image_field, list) and len(image_field) > 0:
                url = image_field[0].get("url")

            if not url:
                continue

            # Find video_id by title match
            video_row = await conn.fetchrow(
                "SELECT id FROM videos WHERE tenant_id = $1 AND title = $2 LIMIT 1",
                tenant_id, video_title,
            )
            if not video_row:
                continue

            video_id = video_row["id"]

            try:
                await conn.execute(
                    """INSERT INTO assets (tenant_id, video_id, asset_type, scene_number, image_index, url, prompt, status)
                       VALUES ($1, $2, 'image', $3, $4, $5, $6, $7)
                       ON CONFLICT DO NOTHING""",
                    tenant_id, video_id, scene_number, image_index, url, prompt, status,
                )
            except Exception as e:
                print(f"  Error upserting asset: {e}")

    return len(records)


async def main():
    """Run sync cycle."""
    if not AIRTABLE_API_KEY:
        print("ERROR: AIRTABLE_API_KEY not set")
        sys.exit(1)
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Starting sync...")

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)

    try:
        # Get tenant ID
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id FROM tenants WHERE slug = 'eff' LIMIT 1")
            if not row:
                print("ERROR: No tenant found with slug 'eff'. Run the schema SQL first.")
                return
            tenant_id = str(row["id"])

        print(f"  Tenant: {tenant_id}")

        # Sync videos
        video_count = await sync_videos(pool, tenant_id)
        print(f"  Synced {video_count} videos")

        # Sync assets
        asset_count = await sync_assets(pool, tenant_id)
        print(f"  Synced {asset_count} assets")

        # Log sync activity
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO bot_activity (tenant_id, bot_name, status, message)
                   VALUES ($1, 'airtable_sync', 'completed', $2)""",
                tenant_id, f"Synced {video_count} videos, {asset_count} assets",
            )

        print("  Sync complete!")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
