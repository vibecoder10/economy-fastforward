"""Supabase Adapter — Drop-in replacement for AirtableClient.

Implements the same method signatures as AirtableClient so pipeline skills
work unchanged. Reads/writes go to Supabase PostgreSQL instead of Airtable.

Key design: Returns dicts with Airtable-style field names (Title Case) because
pipeline skills read fields by those names (e.g., idea["Video Title"]).
The adapter translates between Airtable field names and Supabase column names.

Uses SYNCHRONOUS psycopg2 because pipeline skills call airtable methods
synchronously from within an async context. asyncpg + run_until_complete
would deadlock.
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg2
import psycopg2.extras

# auth.get_tenant_id returns uuid.UUID objects; psycopg2 can't adapt UUID
# params without this ("can't adapt type 'UUID'" killed a research save).
psycopg2.extras.register_uuid()


# Column names interpolated into f-string SQL must match this allowlist.
# Values come from the FIELD_MAP dicts below (all hand-written constants),
# so in practice nothing hostile reaches here — but if a future refactor
# accidentally sources column names from user input, this raises instead
# of producing a SQL-injection vector.
_SAFE_COLUMN_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _safe_col(name: str) -> str:
    """Validate a column name before use in dynamic SQL. Mirrors
    database.safe_column; this module uses psycopg2 (sync) not asyncpg,
    hence the local copy to avoid an async-module import."""
    if not isinstance(name, str) or not _SAFE_COLUMN_RE.match(name):
        raise ValueError(f"Invalid column name: {name!r}")
    return name


def _get_conn():
    """Get a synchronous psycopg2 connection."""
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _fetch_all(query: str, args: tuple = ()) -> list:
    """Execute query, return list of dicts."""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, args)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def _fetch_one(query: str, args: tuple = ()) -> Optional[dict]:
    """Execute query, return single dict or None."""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, args)
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def _execute(query: str, args: tuple = ()) -> str:
    """Execute INSERT/UPDATE/DELETE, return status."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(query, args)
            conn.commit()
            return cur.statusmessage
    finally:
        conn.close()


# ── Field Name Mappings ──────────────────────────────────────────────────────
# Airtable field name → Supabase column name
# Pipeline skills use Airtable names; Supabase uses snake_case.

IDEA_FIELD_MAP = {
    # Core
    "Status": "status",
    "Video Title": "video_title",
    "Hook Script": "hook_script",
    "Past Context": "past_context",
    "Present Parallel": "present_parallel",
    "Future Prediction": "future_prediction",
    "Thumbnail Prompt": "thumbnail_prompt",
    "Writer Guidance": "writer_guidance",
    "Original DNA": "original_dna",
    "Source": "source",
    # Research
    "Framework Angle": "framework_angle",
    "Headline": "headline",
    "Timeliness Score": "timeliness_score",
    "Audience Fit Score": "audience_fit_score",
    "Content Gap Score": "content_gap_score",
    "Source URLs": "source_urls",
    "Executive Hook": "executive_hook",
    "Thesis": "thesis",
    "Date Surfaced": "date_surfaced",
    "Research Payload": "research_payload",
    "Thematic Framework": "thematic_framework",
    # Style overrides
    "Image Style Override": "image_style_override",
    "Thumbnail Style Override": "thumbnail_style_override",
    "Accent Color": "accent_color",
    "Image Model Override": "image_model_override",
    "Visual Style": "visual_style",
    # Visual consistency
    "Story Bible": "story_bible",
    "Character Reference": "character_reference_url",
    # Pipeline state
    "Script": "script",
    "Script Validation": "script_validation",
    "Scene File Path": "scene_file_path",
    "Drive Folder ID": "drive_folder_id",
    "Drive Folder Link": "drive_folder_link",
    "Core Image": "core_image_url",
    "Video Length (min)": "video_length_minutes",
    # YouTube / Upload
    "Upload Status": "upload_status",
    "YouTube Video ID": "youtube_video_id",
    "YouTube URL": "youtube_url",
    "Upload Date": "upload_date",
    "Final Video": "final_video_url",
    "Final Video URL": "final_video_url",
    # SEO
    "SEO Description": "seo_description",
    "SEO Tags": "seo_tags",
    "SEO Hashtags": "seo_hashtags",
    # Performance
    "Views": "views",
    "Likes": "likes",
    "Comments": "comments",
    "Subscribers Gained": "subscribers_gained",
    "Avg View Duration (s)": "avg_view_duration_seconds",
    "Avg Retention (%)": "avg_retention",
    "Watch Time (hours)": "watch_time_hours",
    "Impressions": "impressions",
    "CTR (%)": "ctr",
    "Views 24h": "views_24h",
    "Views 48h": "views_48h",
    "Views 7d": "views_7d",
    "Views 30d": "views_30d",
    "CTR 12h (%)": "ctr_12h",
    "CTR 24h (%)": "ctr_24h",
    "CTR 48h (%)": "ctr_48h",
    "Retention 48h (%)": "retention_48h",
    "Last Analytics Sync": "last_analytics_sync",
    # Post-mortem
    "Post-Mortem 48h": "post_mortem_48h",
    "Post-Mortem 7d": "post_mortem_7d",
    "Performance Verdict": "performance_verdict",
    # Thumbnail
    "Thumbnail Text": "thumbnail_text",
    "Thumbnail Palette": "thumbnail_palette",
    "Summary": "summary",
    # Storyboard
    "Storyboard Status": "storyboard_status",
    "Storyboard Preview": "storyboard_preview_url",
    "Storyboard Beat Count": "storyboard_beat_count",
    "Video Model": "video_model",
    # Curiosity gap
    "Curiosity Structure": "curiosity_structure",
    "Structure Confidence": "structure_confidence",
    "Thumbnail Approach": "thumbnail_approach",
    "Structure Source": "structure_source",
    "Pattern Library Snapshot": "pattern_library_snapshot",
    "Title Poll Result": "title_poll_result",
    "Poll Closed": "poll_closed",
    # Metadata
    "Reference URL": "reference_url",
    "Idea Reasoning": "idea_reasoning",
    "Source Views": "source_views",
    "Source Channel": "source_channel",
    "Google Drive Folder ID": "drive_folder_id",
    "Thumbnail": "thumbnail_url",
    "Pipeline Mode": "pipeline_mode",
    "Notes": "notes",
}

# Reverse map: Supabase column → Airtable field name
IDEA_COLUMN_MAP = {v: k for k, v in IDEA_FIELD_MAP.items()}

SCRIPT_FIELD_MAP = {
    "scene": "scene",
    "Scene text": "scene_text",
    "Title": "title",
    "Voice ID": "voice_id",
    "Script Status": "script_status",
    "Voice Status": "voice_status",
    "Voice Over": "voice_over_url",
    "Sources": "sources",
    "Psych Angle": "psych_angle",
    "SFX Status": "sfx_status",
    "Sound Map": "sound_map",
    "Story Board On/OFF": "storyboard_on_off",
    "Storyboard Prompts": "storyboard_prompts",
    "Storyboard Beat Count": "storyboard_beat_count",
    "Storyboard Status": "storyboard_status",
    "Storyboard 1": "storyboard_1_url",
    "Storyboard 2": "storyboard_2_url",
    "Storyboard 3": "storyboard_3_url",
    "Storyboard 4": "storyboard_4_url",
    "Storyboard 5": "storyboard_5_url",
}

SCRIPT_COLUMN_MAP = {v: k for k, v in SCRIPT_FIELD_MAP.items()}

IMAGE_FIELD_MAP = {
    "Scene": "scene",
    "Image Index": "image_index",
    "Sentence Index": "sentence_index",
    "Sentence Text": "sentence_text",
    "Image Prompt": "image_prompt",
    "Original Image Prompt": "original_image_prompt",
    "Shot Type": "shot_type",
    "Video Title": "video_title",
    "Aspect Ratio": "aspect_ratio",
    "Status": "status",
    "Duration (s)": "duration_seconds",
    "Image": "image_url",
    "Video": "video_url",
    "Video Prompt": "video_prompt",
    "Video Status": "video_status",
    "Drive Image URL": "drive_image_url",
    "Hero Shot": "hero_shot",
    "Video Clip URL": "video_clip_url",
    "Animation Status": "animation_status",
    "Video Duration": "video_duration",
    "Sound Prompt": "sound_prompt",
    "Sound Effect": "sound_effect_url",
    "Sound Volume": "sound_volume",
    "Storyboard Grid URL": "storyboard_grid_url",
    "Panel Position": "panel_position",
    "Generation Method": "generation_method",
    "Clip Duration": "clip_duration",
    "Camera Movement": "camera_movement",
    "Assigned Video Duration": "assigned_video_duration",
    "Estimated Clip Cost": "estimated_clip_cost",
}

IMAGE_COLUMN_MAP = {v: k for k, v in IMAGE_FIELD_MAP.items()}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _row_to_idea(row: dict) -> dict:
    """Convert a Supabase videos row to Airtable-shaped idea dict."""
    result = {"id": str(row.get("id", ""))}
    for col, val in row.items():
        airtable_name = IDEA_COLUMN_MAP.get(col)
        if airtable_name:
            # Special handling for JSONB fields → pipeline expects JSON strings
            if col in ("research_payload", "original_dna", "story_bible") and isinstance(val, dict):
                result[airtable_name] = json.dumps(val)
            # Attachments: pipeline expects [{"url": "..."}] format
            elif col == "character_reference_url" and val:
                result[airtable_name] = [{"url": val}]
            elif col == "thumbnail_url" and val:
                result["Thumbnail"] = [{"url": val}]
            elif col == "core_image_url" and val:
                result["Core Image"] = [{"url": val}]
            elif col == "image_model_override" and val:
                # Multiple Select in Airtable = list
                result[airtable_name] = [val] if isinstance(val, str) else val
            else:
                result[airtable_name] = val
    return result


def _row_to_script(row: dict) -> dict:
    """Convert a Supabase scripts row to Airtable-shaped script dict."""
    result = {"id": str(row.get("id", ""))}
    for col, val in row.items():
        airtable_name = SCRIPT_COLUMN_MAP.get(col)
        if airtable_name:
            # Voice Over attachment format
            if col == "voice_over_url" and val:
                result[airtable_name] = [{"url": val}]
            # Storyboard attachment format
            elif col in ("storyboard_1_url", "storyboard_2_url", "storyboard_3_url", "storyboard_4_url", "storyboard_5_url") and val:
                result[airtable_name] = [{"url": val}]
            else:
                result[airtable_name] = val
    # Also include title from the video
    if "title" in row:
        result["Title"] = row["title"]
    return result


def _row_to_image(row: dict) -> dict:
    """Convert a Supabase assets row to Airtable-shaped image dict."""
    result = {"id": str(row.get("id", ""))}
    for col, val in row.items():
        airtable_name = IMAGE_COLUMN_MAP.get(col)
        if airtable_name:
            # Image/Video attachment format
            if col == "image_url" and val:
                result[airtable_name] = [{"url": val}]
            elif col == "video_url" and val:
                result[airtable_name] = [{"url": val}]
            elif col == "sound_effect_url" and val:
                result[airtable_name] = [{"url": val}]
            elif col == "status" and val:
                # Capitalize to match Airtable conventions (pending->Pending, done->Done)
                result[airtable_name] = val.capitalize()
            else:
                result[airtable_name] = val
    # Structured per-panel location (not in the Airtable map) — the storyboard
    # bot reads it to pick the matching environment reference for each grid.
    result["location_id"] = row.get("location_id")
    return result


def _idea_fields_to_columns(fields: dict) -> dict:
    """Convert Airtable field names to Supabase column names for UPDATE."""
    result = {}
    for airtable_name, value in fields.items():
        col = IDEA_FIELD_MAP.get(airtable_name)
        if col:
            # Handle attachment → URL extraction
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict) and "url" in value[0]:
                result[col] = value[0]["url"]
            # Handle JSONB fields by adapting Python objects and JSON strings explicitly.
            elif col in ("research_payload", "original_dna", "story_bible") and isinstance(value, str):
                try:
                    result[col] = psycopg2.extras.Json(json.loads(value))
                except (json.JSONDecodeError, TypeError):
                    result[col] = value
            elif col in ("research_payload", "original_dna", "story_bible") and isinstance(value, (dict, list)):
                result[col] = psycopg2.extras.Json(value)
            else:
                result[col] = value
    return result


def _get_video_id_for_title(title: str) -> str:
    """Build subquery to find video_id from title."""
    return f"(SELECT id FROM videos WHERE video_title = ${{}} LIMIT 1)"


# ── SupabaseAdapter ──────────────────────────────────────────────────────────

class SupabaseAdapter:
    """Drop-in replacement for AirtableClient. Same methods, Supabase backend.

    All methods are SYNCHRONOUS (pipeline skills call them from sync context).
    Uses psycopg2 for sync PostgreSQL access.
    """

    def __init__(self, tenant_id: str = None):
        self.tenant_id = tenant_id

    def _tw(self, alias: str = "") -> tuple:
        """Tenant-isolation predicate for title/status lookups.

        Returns (" AND <col> = %s", [tenant_id]) when a tenant is bound, else
        ("", []). Every lookup that resolves a row by TITLE or STATUS must AND
        this in — without it, two tenants sharing a video title or pipeline
        status read (or DELETE) each other's rows. id-based reads add it as
        defense in depth. The else branch keeps standalone/CLI callers (no
        tenant) working unchanged.
        """
        if not self.tenant_id:
            return "", []
        col = f"{alias}.tenant_id" if alias else "tenant_id"
        return f" AND {col} = %s", [self.tenant_id]

    # ── Idea Concepts (videos table) ─────────────────────────────────────

    def get_idea(self, record_id: str) -> Optional[dict]:
        """Fetch single video by ID (tenant-scoped)."""
        tw, tp = self._tw()
        row = _fetch_one(f"SELECT * FROM videos WHERE id = %s{tw}", (record_id, *tp))
        if not row:
            row = _fetch_one(
                f"SELECT * FROM videos WHERE airtable_record_id = %s{tw}", (record_id, *tp)
            )
        return _row_to_idea(row) if row else None

    def get_ideas_by_status(self, status: str, limit: int = 1) -> list:
        """Filter videos by pipeline status (tenant-scoped)."""
        from status_map import to_supabase
        supabase_status = to_supabase(status) if " " in status else status
        tw, tp = self._tw()
        rows = _fetch_all(
            f"SELECT * FROM videos WHERE status = %s{tw} ORDER BY created_at DESC LIMIT %s",
            (supabase_status, *tp, limit),
        )
        return [_row_to_idea(r) for r in rows]

    def get_ideas_ready_for_scripting(self, limit: int = 1) -> list:
        return self.get_ideas_by_status("Ready For Scripting", limit)

    def get_all_ideas(self) -> list:
        """Fetch all videos (tenant-scoped)."""
        if self.tenant_id:
            rows = _fetch_all(
                "SELECT * FROM videos WHERE tenant_id = %s ORDER BY created_at DESC",
                (self.tenant_id,),
            )
        else:
            rows = _fetch_all("SELECT * FROM videos ORDER BY created_at DESC")
        return [_row_to_idea(r) for r in rows]

    def find_idea_by_title(self, title: str) -> Optional[dict]:
        """Find video by exact title (tenant-scoped); fuzzy fallback stays in-tenant."""
        tw, tp = self._tw()
        row = _fetch_one(
            f"SELECT * FROM videos WHERE video_title = %s{tw} LIMIT 1", (title, *tp)
        )
        if not row:
            # Fuzzy fallback: ILIKE — still scoped to this tenant
            row = _fetch_one(
                f"SELECT * FROM videos WHERE video_title ILIKE %s{tw} LIMIT 1",
                (f"%{title}%", *tp),
            )
        return _row_to_idea(row) if row else None

    def create_idea(self, idea_data: dict, source: str = "storyengine") -> dict:
        """Create a new video."""
        video_id = str(uuid.uuid4())
        title = idea_data.get("viral_title") or idea_data.get("Video Title") or idea_data.get("video_title", "Untitled")

        # Extract narrative fields
        narrative = idea_data.get("narrative_logic", {})

        _execute(
            """INSERT INTO videos (id, tenant_id, video_title, status, source,
               hook_script, past_context, present_parallel, future_prediction,
               thumbnail_prompt, writer_guidance, original_dna, headline)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                video_id, self.tenant_id, title, "idea_logged", source,
                idea_data.get("hook_script", ""),
                narrative.get("past_context", "") if isinstance(narrative, dict) else idea_data.get("past_context", ""),
                narrative.get("present_parallel", "") if isinstance(narrative, dict) else idea_data.get("present_parallel", ""),
                narrative.get("future_prediction", "") if isinstance(narrative, dict) else idea_data.get("future_prediction", ""),
                idea_data.get("thumbnail_visual", ""),
                idea_data.get("writer_guidance", ""),
                json.dumps(idea_data.get("original_dna")) if idea_data.get("original_dna") else None,
                idea_data.get("headline", title),
            ),
        )

        row = _fetch_one("SELECT * FROM videos WHERE id = %s", (video_id,))
        return _row_to_idea(row)

    def update_idea_status(self, record_id: str, status: str) -> dict:
        """Update video status."""
        from status_map import to_supabase
        supabase_status = to_supabase(status) if " " in status else status
        _execute(
            "UPDATE videos SET status = %s, updated_at = now() WHERE id = %s",
            (supabase_status, record_id),
        )
        return {"id": record_id}

    def update_idea_field(self, record_id: str, field_name: str, value: Any) -> dict:
        """Update a single field on a video."""
        return self.update_idea_fields(record_id, {field_name: value})

    def update_idea_fields(self, record_id: str, fields: dict) -> dict:
        """Update multiple fields on a video.

        Returns dict with 'id' and all written Airtable-named fields,
        so verification checks like `if 'Script' not in result` work.
        """
        columns = _idea_fields_to_columns(fields)
        if not columns:
            return {"id": record_id, **fields}

        # Build dynamic UPDATE with %s placeholders
        sets = []
        args = []
        for col, val in columns.items():
            sets.append(f"{_safe_col(col)} = %s")
            args.append(val)
        args.append(record_id)

        query = f"UPDATE videos SET {', '.join(sets)}, updated_at = now() WHERE id = %s"
        try:
            _execute(query, tuple(args))
        except Exception as e:
            # Graceful degradation: skip unknown columns
            print(f"  Warning: update_idea_fields partial failure: {e}")
            for col, val in columns.items():
                try:
                    _execute(
                        f"UPDATE videos SET {_safe_col(col)} = %s, updated_at = now() WHERE id = %s",
                        (val, record_id),
                    )
                except Exception:
                    pass
        # Return the fields that were written (Airtable names) for verification
        return {"id": record_id, **fields}

    def update_idea_thumbnail(self, record_id: str, thumbnail_url: str) -> dict:
        """Update thumbnail URL."""
        _execute(
            "UPDATE videos SET thumbnail_url = %s, updated_at = now() WHERE id = %s",
            (thumbnail_url, record_id),
        )
        return {"id": record_id}

    # ── Scripts Table ────────────────────────────────────────────────────

    def get_scripts_by_title(self, title: str) -> list:
        """Get all script scenes for a video.

        PREFERS the explicitly-loaded current video (set by the executor) over
        the title — duplicate titles otherwise read another video's scenes.
        """
        current_vid = getattr(self, "current_video_id", None)
        tw, tp = self._tw("v")
        if current_vid:
            rows = _fetch_all(
                f"""SELECT s.*, v.video_title as title FROM scripts s
                   JOIN videos v ON s.video_id = v.id
                   WHERE s.video_id = %s{tw}
                   ORDER BY s.scene""",
                (current_vid, *tp),
            )
            return [_row_to_script(r) for r in rows]
        rows = _fetch_all(
            f"""SELECT s.*, v.video_title as title FROM scripts s
               JOIN videos v ON s.video_id = v.id
               WHERE v.video_title = %s{tw}
               ORDER BY s.scene""",
            (title, *tp),
        )
        if not rows:
            # Fuzzy fallback — still scoped to this tenant
            rows = _fetch_all(
                f"""SELECT s.*, v.video_title as title FROM scripts s
                   JOIN videos v ON s.video_id = v.id
                   WHERE v.video_title ILIKE %s{tw}
                   ORDER BY s.scene""",
                (f"%{title}%", *tp),
            )
        return [_row_to_script(r) for r in rows]

    def get_scripts_to_create(self) -> list:
        """Get scripts with status 'Create' (tenant-scoped)."""
        tw, tp = self._tw("s")
        rows = _fetch_all(
            f"""SELECT s.*, v.video_title as title FROM scripts s
               JOIN videos v ON s.video_id = v.id
               WHERE s.script_status = 'Create'{tw}
               ORDER BY s.scene""",
            tuple(tp),
        )
        return [_row_to_script(r) for r in rows]

    def create_script_record(
        self,
        scene_number: int,
        scene_text: str,
        title: str,
        voice_id: str = "UgBBYS2sOqTuMpoF3BR0",
        sources: str = "",
        psych_angle: str = "",
    ) -> dict:
        """Create a script scene record."""
        # Resolve the target video. PREFER the explicitly-loaded current video
        # (the executor sets current_video_id when it loads the idea) — resolving
        # by TITLE is ambiguous when two videos share a title, which silently
        # writes scenes to the wrong (oldest LIMIT 1) video. Title is only a
        # fallback for legacy/no-context callers.
        current_vid = getattr(self, "current_video_id", None)
        tw, tp = self._tw()
        video = None
        if current_vid:
            video = _fetch_one(
                f"SELECT id, tenant_id FROM videos WHERE id = %s{tw} LIMIT 1", (current_vid, *tp)
            )
        if not video:
            video = _fetch_one(
                f"SELECT id, tenant_id FROM videos WHERE video_title = %s{tw} LIMIT 1", (title, *tp)
            )
        if not video:
            video = _fetch_one(
                f"SELECT id, tenant_id FROM videos WHERE video_title ILIKE %s{tw} LIMIT 1",
                (f"%{title}%", *tp),
            )
        if not video:
            print(f"  Warning: No video found (id={current_vid!r}, title='{title}') — creating script without video_id")
            video = {"id": None, "tenant_id": self.tenant_id}

        script_id = str(uuid.uuid4())
        _execute(
            """INSERT INTO scripts (id, tenant_id, video_id, scene, scene_text, title,
               voice_id, script_status, sources, psych_angle)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                script_id, video["tenant_id"] or self.tenant_id, video["id"],
                scene_number, scene_text, title,
                voice_id, "Create",
                sources if scene_number == 1 else "",  # Sources only on scene 1
                psych_angle,
            ),
        )
        return {"id": script_id, "scene": scene_number, "Scene text": scene_text, "Title": title}

    def update_script_record(self, record_id: str, updates: dict) -> dict:
        """Update script fields."""
        columns = {}
        for airtable_name, val in updates.items():
            col = SCRIPT_FIELD_MAP.get(airtable_name)
            if col:
                # Handle attachment format
                if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict) and "url" in val[0]:
                    columns[col] = val[0]["url"]
                else:
                    columns[col] = val

        if columns:
            sets = []
            args = []
            for col, val in columns.items():
                sets.append(f"{_safe_col(col)} = %s")
                args.append(val)
            sets.append("updated_at = now()")
            args.append(record_id)
            _execute(
                f"UPDATE scripts SET {', '.join(sets)} WHERE id = %s",
                tuple(args),
            )
        return {"id": record_id}

    def mark_script_finished(self, record_id: str, voice_over_url: Optional[str] = None) -> dict:
        """Mark script as finished with optional voice URL."""
        if voice_over_url:
            _execute(
                """UPDATE scripts SET script_status = 'Finished', voice_status = 'Done',
                   voice_over_url = %s WHERE id = %s""",
                (voice_over_url, record_id),
            )
        else:
            _execute(
                "UPDATE scripts SET script_status = 'Finished' WHERE id = %s",
                (record_id,),
            )
        return {"id": record_id}

    def delete_scripts_for_video(self, video_title: str) -> int:
        """Delete all scripts for a video (tenant-scoped — never touches another tenant)."""
        tw, tp = self._tw()
        result = _execute(
            f"""DELETE FROM scripts WHERE video_id IN
               (SELECT id FROM videos WHERE video_title = %s{tw})""",
            (video_title, *tp),
        )
        # psycopg2 returns "DELETE N"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0

    # ── Images/Assets Table ──────────────────────────────────────────────

    def get_pending_images(self) -> list:
        """Get all pending images (tenant-scoped)."""
        tw, tp = self._tw()
        rows = _fetch_all(
            f"SELECT * FROM assets WHERE status = 'pending'{tw} ORDER BY scene, image_index",
            tuple(tp),
        )
        return [_row_to_image(r) for r in rows]

    def get_all_images_for_video(self, video_title: str) -> list:
        """Get all assets for a video (prefers current video, tenant-scoped).

        PREFERS the explicitly-loaded current video (set by the executor) over
        the title — duplicate or soft-deleted same-titled videos otherwise read
        another video's assets. Title is a deleted-excluding, tenant-scoped fallback.
        """
        tw, tp = self._tw("v")
        current_vid = getattr(self, "current_video_id", None)
        if current_vid:
            rows = _fetch_all(
                f"""SELECT a.* FROM assets a
                   JOIN videos v ON a.video_id = v.id
                   WHERE a.video_id = %s{tw}
                   ORDER BY a.scene, a.image_index""",
                (current_vid, *tp),
            )
            return [_row_to_image(r) for r in rows]
        rows = _fetch_all(
            f"""SELECT a.* FROM assets a
               JOIN videos v ON a.video_id = v.id
               WHERE v.video_title = %s AND v.deleted_at IS NULL{tw}
               ORDER BY a.scene, a.image_index""",
            (video_title, *tp),
        )
        return [_row_to_image(r) for r in rows]

    def get_pending_images_for_video(self, video_title: str) -> list:
        """Get pending images for a specific video (prefers current video, tenant-scoped)."""
        tw, tp = self._tw("v")
        current_vid = getattr(self, "current_video_id", None)
        if current_vid:
            rows = _fetch_all(
                f"""SELECT a.* FROM assets a
                   JOIN videos v ON a.video_id = v.id
                   WHERE a.video_id = %s AND a.status = 'pending'{tw}
                   ORDER BY a.scene, a.image_index""",
                (current_vid, *tp),
            )
            return [_row_to_image(r) for r in rows]
        rows = _fetch_all(
            f"""SELECT a.* FROM assets a
               JOIN videos v ON a.video_id = v.id
               WHERE v.video_title = %s AND v.deleted_at IS NULL AND a.status = 'pending'{tw}
               ORDER BY a.scene, a.image_index""",
            (video_title, *tp),
        )
        return [_row_to_image(r) for r in rows]

    def get_images_ready_for_video_generation(self, video_title: str) -> list:
        """Get images ready for video clip generation (prefers current video, tenant-scoped)."""
        tw, tp = self._tw("v")
        current_vid = getattr(self, "current_video_id", None)
        if current_vid:
            rows = _fetch_all(
                f"""SELECT a.* FROM assets a
                   JOIN videos v ON a.video_id = v.id
                   WHERE a.video_id = %s AND a.status = 'done'
                   AND (a.video_url IS NULL OR a.video_url = ''){tw}
                   ORDER BY a.scene, a.image_index""",
                (current_vid, *tp),
            )
            return [_row_to_image(r) for r in rows]
        rows = _fetch_all(
            f"""SELECT a.* FROM assets a
               JOIN videos v ON a.video_id = v.id
               WHERE v.video_title = %s AND v.deleted_at IS NULL AND a.status = 'done'
               AND (a.video_url IS NULL OR a.video_url = ''){tw}
               ORDER BY a.scene, a.image_index""",
            (video_title, *tp),
        )
        return [_row_to_image(r) for r in rows]

    def create_concept_record(
        self,
        scene_number: int,
        concept_index: int,
        sentence_text: str,
        image_prompt: str,
        composition: str,
        video_title: str,
        aspect_ratio: str = "16:9",
        location_id: Optional[str] = None,
    ) -> dict:
        """Create an image/asset record."""
        # PREFER the explicitly-loaded current video (the executor sets
        # current_video_id) — resolving by title LIMIT 1 silently writes assets
        # to the wrong (often soft-deleted) same-titled video, which is how a live
        # video ends up with ZERO assets while a deleted twin holds them. Title is
        # a deleted-excluding, tenant-scoped fallback for legacy callers.
        tw, tp = self._tw()
        current_vid = getattr(self, "current_video_id", None)
        video = None
        if current_vid:
            video = _fetch_one(
                f"SELECT id, tenant_id FROM videos WHERE id = %s{tw} LIMIT 1",
                (current_vid, *tp),
            )
        if not video:
            video = _fetch_one(
                f"SELECT id, tenant_id FROM videos WHERE video_title = %s AND deleted_at IS NULL{tw} LIMIT 1",
                (video_title, *tp),
            )
        if not video:
            video = _fetch_one(
                f"SELECT id, tenant_id FROM videos WHERE video_title ILIKE %s AND deleted_at IS NULL{tw} LIMIT 1",
                (f"%{video_title}%", *tp),
            )

        asset_id = str(uuid.uuid4())
        _execute(
            """INSERT INTO assets (id, tenant_id, video_id, scene, image_index,
               sentence_index, sentence_text, image_prompt, shot_type,
               video_title, aspect_ratio, status, location_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                asset_id, video["tenant_id"] if video else self.tenant_id,
                video["id"] if video else None,
                scene_number, concept_index, concept_index,
                sentence_text, image_prompt, composition,
                video_title, aspect_ratio, "pending", location_id,
            ),
        )
        return {"id": asset_id, "Scene": scene_number, "Image Index": concept_index}

    def update_image_record(self, record_id: str, image_url: str, drive_url: Optional[str] = None) -> dict:
        """Update image with generated URL."""
        if drive_url:
            _execute(
                "UPDATE assets SET image_url = %s, drive_image_url = %s, status = 'done' WHERE id = %s",
                (image_url, drive_url, record_id),
            )
        else:
            _execute(
                "UPDATE assets SET image_url = %s, status = 'done' WHERE id = %s",
                (image_url, record_id),
            )
        return {"id": record_id}

    def update_image_video_prompt(self, record_id: str, prompt: str) -> dict:
        """Update video motion prompt for an image."""
        _execute(
            "UPDATE assets SET video_prompt = %s WHERE id = %s",
            (prompt, record_id),
        )
        return {"id": record_id}

    def update_image_video_url(self, record_id: str, video_url: str) -> dict:
        """Update video clip URL."""
        _execute(
            "UPDATE assets SET video_url = %s, video_status = 'done' WHERE id = %s",
            (video_url, record_id),
        )
        return {"id": record_id}

    def update_image_animation_fields(
        self, record_id: str, shot_type: str = None, is_hero_shot: bool = None,
        video_clip_url: str = None, animation_status: str = None,
        video_duration: float = None,
    ) -> dict:
        """Update animation-related fields on an asset."""
        fields = {}
        if shot_type is not None:
            fields["shot_type"] = shot_type
        if is_hero_shot is not None:
            fields["hero_shot"] = is_hero_shot
        if video_clip_url is not None:
            fields["video_clip_url"] = video_clip_url
        if animation_status is not None:
            fields["animation_status"] = animation_status
        if video_duration is not None:
            fields["video_duration"] = video_duration

        if fields:
            sets = []
            args = []
            for col, val in fields.items():
                sets.append(f"{_safe_col(col)} = %s")
                args.append(val)
            args.append(record_id)
            _execute(
                f"UPDATE assets SET {', '.join(sets)} WHERE id = %s",
                tuple(args),
            )
        return {"id": record_id}

    def update_image_prompt_fields(self, record_id: str, image_prompt: str, shot_type: str,
                                   location_id: Optional[str] = None) -> dict:
        """Update prompt and shot type (and the structured location when known)."""
        if location_id is not None:
            _execute(
                "UPDATE assets SET image_prompt = %s, shot_type = %s, location_id = %s WHERE id = %s",
                (image_prompt, shot_type, location_id, record_id),
            )
        else:
            _execute(
                "UPDATE assets SET image_prompt = %s, shot_type = %s WHERE id = %s",
                (image_prompt, shot_type, record_id),
            )
        return {"id": record_id}

    def update_image_sound_prompt(self, record_id: str, sound_prompt: str) -> dict:
        """Update sound prompt."""
        _execute(
            "UPDATE assets SET sound_prompt = %s WHERE id = %s",
            (sound_prompt, record_id),
        )
        return {"id": record_id}

    def update_image_sound_effect(self, record_id: str, sound_url: str, volume: float = 0.15) -> dict:
        """Update sound effect URL and volume."""
        _execute(
            "UPDATE assets SET sound_effect_url = %s, sound_volume = %s WHERE id = %s",
            (sound_url, volume, record_id),
        )
        return {"id": record_id}

    def delete_images_for_video(self, video_title: str) -> int:
        """Delete all assets for a video (tenant-scoped — never touches another tenant)."""
        tw, tp = self._tw()
        result = _execute(
            f"""DELETE FROM assets WHERE video_id IN
               (SELECT id FROM videos WHERE video_title = %s{tw})""",
            (video_title, *tp),
        )
        # psycopg2 returns "DELETE N"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0

    # ── Competitor Videos Table ───────────────────────────────────────────

    def get_all_competitor_video_ids(self) -> set:
        """Get set of all competitor video IDs for deduplication."""
        if self.tenant_id:
            rows = _fetch_all(
                "SELECT video_id FROM competitor_videos WHERE tenant_id = %s",
                (self.tenant_id,),
            )
        else:
            rows = _fetch_all("SELECT video_id FROM competitor_videos")
        return {r["video_id"] for r in rows}

    def create_competitor_video(self, video_data: dict) -> dict:
        """Create a competitor video record."""
        vid = str(uuid.uuid4())
        _execute(
            """INSERT INTO competitor_videos (id, tenant_id, video_id, title, url, channel, channel_url,
               views, vph, hours_old, published_date, scrape_date)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (tenant_id, video_id) DO UPDATE SET
                 views = EXCLUDED.views, vph = EXCLUDED.vph,
                 hours_old = EXCLUDED.hours_old, scrape_date = EXCLUDED.scrape_date""",
            (
                vid, self.tenant_id,
                video_data.get("Video ID"), video_data.get("Title"),
                video_data.get("URL"), video_data.get("Channel"),
                video_data.get("Channel URL"), video_data.get("Views"),
                video_data.get("VPH"), video_data.get("Hours Old"),
                video_data.get("Published Date"), video_data.get("Scrape Date"),
            ),
        )
        return {"id": vid}

    def batch_create_competitor_videos(self, videos: list) -> list:
        """Batch create competitor videos."""
        return [self.create_competitor_video(v) for v in videos]

    # ── Competitor Channels ───────────────────────────────────────────────

    def get_active_competitor_channels(self) -> list:
        """Get active competitor channels."""
        rows = _fetch_all(
            "SELECT * FROM competitor_channels WHERE active = true"
        )
        # Return with Airtable-style field names
        return [
            {
                "id": str(r["id"]),
                "Channel Name": r.get("channel_name"),
                "Channel URL": r.get("channel_url"),
                "Category": r.get("category"),
                "Active": r.get("active"),
                "Last Scraped": r.get("last_scraped"),
                "Notes": r.get("notes"),
            }
            for r in rows
        ]

    def update_channel_last_scraped(self, record_id: str) -> dict:
        """Update last scraped timestamp."""
        _execute(
            "UPDATE competitor_channels SET last_scraped = now() WHERE id = %s",
            (record_id,),
        )
        return {"id": record_id}

    # ── Osiris Learnings ─────────────────────────────────────────────────

    def get_all_learnings(self, category: str = None, active_only: bool = True) -> list:
        """Get learned patterns."""
        conditions = []
        args = []
        if category:
            args.append(category)
            conditions.append("category = %s")
        if active_only:
            conditions.append("active = true")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = _fetch_all(
            f"SELECT * FROM learnings {where} ORDER BY confidence DESC",
            tuple(args),
        )
        return [
            {
                "id": str(r["id"]),
                "Category": r.get("category"),
                "Pattern": r.get("pattern"),
                "Confidence": r.get("confidence"),
                "Sample Size": r.get("sample_size"),
                "Avg CTR": r.get("avg_ctr"),
                "Avg Retention": r.get("avg_retention"),
                "Source Videos": r.get("source_videos"),
                "Active": r.get("active"),
            }
            for r in rows
        ]

    def create_learning(self, learning: dict) -> dict:
        """Create a learning record."""
        lid = str(uuid.uuid4())
        _execute(
            """INSERT INTO learnings (id, category, pattern, confidence, sample_size,
               avg_ctr, avg_retention, source_videos, active)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                lid, learning.get("Category"), learning.get("Pattern"),
                learning.get("Confidence", 50), learning.get("Sample Size", 1),
                learning.get("Avg CTR"), learning.get("Avg Retention"),
                learning.get("Source Videos"), learning.get("Active", True),
            ),
        )
        return {"id": lid}

    def update_learning(self, record_id: str, updates: dict) -> dict:
        """Update a learning record."""
        field_map = {
            "Category": "category", "Pattern": "pattern", "Confidence": "confidence",
            "Sample Size": "sample_size", "Avg CTR": "avg_ctr",
            "Avg Retention": "avg_retention", "Source Videos": "source_videos",
            "Active": "active", "Last Updated": "last_updated",
        }
        cols = {}
        for at_name, val in updates.items():
            col = field_map.get(at_name)
            if col:
                cols[col] = val
        if cols:
            sets = []
            args = []
            for col, val in cols.items():
                sets.append(f"{_safe_col(col)} = %s")
                args.append(val)
            args.append(record_id)
            _execute(
                f"UPDATE learnings SET {', '.join(sets)} WHERE id = %s",
                tuple(args),
            )
        return {"id": record_id}

    # ── Title Insights ───────────────────────────────────────────────────

    def create_title_insight(self, insight: dict) -> dict:
        """Create a title insight record."""
        iid = str(uuid.uuid4())
        _execute(
            """INSERT INTO title_insights (id, analysis_date, pattern_type, pattern_name,
               description, example_titles, avg_vph, count, confidence,
               videos_analyzed, vph_threshold)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                iid, insight.get("Analysis Date"), insight.get("Pattern Type"),
                insight.get("Pattern Name"), insight.get("Description"),
                insight.get("Example Titles"), insight.get("Avg VPH"),
                insight.get("Count"), insight.get("Confidence"),
                insight.get("Videos Analyzed"), insight.get("VPH Threshold"),
            ),
        )
        return {"id": iid}

    def batch_create_title_insights(self, insights: list) -> list:
        return [self.create_title_insight(i) for i in insights]

    def get_title_insights(self, pattern_type: str = None, limit: int = 50) -> list:
        """Get title insights."""
        if pattern_type:
            rows = _fetch_all(
                "SELECT * FROM title_insights WHERE pattern_type = %s ORDER BY confidence DESC LIMIT %s",
                (pattern_type, limit),
            )
        else:
            rows = _fetch_all(
                "SELECT * FROM title_insights ORDER BY confidence DESC LIMIT %s",
                (limit,),
            )
        return [
            {
                "id": str(r["id"]),
                "Pattern Type": r.get("pattern_type"),
                "Pattern Name": r.get("pattern_name"),
                "Description": r.get("description"),
                "Example Titles": r.get("example_titles"),
                "Avg VPH": r.get("avg_vph"),
                "Count": r.get("count"),
                "Confidence": r.get("confidence"),
            }
            for r in rows
        ]

    # ── Performance / Analysis ───────────────────────────────────────────

    def get_videos_needing_postmortem(self) -> list:
        """Get videos that need 48h or 7d analysis."""
        rows = _fetch_all(
            """SELECT * FROM videos
               WHERE upload_date IS NOT NULL
               AND (
                   (post_mortem_48h IS NULL AND upload_date < now() - interval '48 hours')
                   OR (post_mortem_7d IS NULL AND upload_date < now() - interval '7 days')
               )
               ORDER BY upload_date DESC"""
        )
        return [_row_to_idea(r) for r in rows]

    # ── Generic ──────────────────────────────────────────────────────────

    def update_record(self, table_name: str, record_id: str, fields: dict) -> dict:
        """Generic record update — dispatches by table name."""
        if "idea" in table_name.lower() or "concept" in table_name.lower():
            return self.update_idea_fields(record_id, fields)
        elif "script" in table_name.lower():
            return self.update_script_record(record_id, fields)
        elif "image" in table_name.lower() or "asset" in table_name.lower():
            columns = {}
            for airtable_name, val in fields.items():
                col = IMAGE_FIELD_MAP.get(airtable_name)
                if not col:
                    continue
                if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict) and "url" in val[0]:
                    columns[col] = val[0]["url"]
                else:
                    columns[col] = val

            if columns:
                sets = []
                args = []
                for col, val in columns.items():
                    sets.append(f"{_safe_col(col)} = %s")
                    args.append(val)
                sets.append("updated_at = now()")
                args.append(record_id)
                _execute(
                    f"UPDATE assets SET {', '.join(sets)} WHERE id = %s",
                    tuple(args),
                )
            return {"id": record_id}
        else:
            print(f"  Warning: update_record for unknown table '{table_name}'")
            return {"id": record_id}
