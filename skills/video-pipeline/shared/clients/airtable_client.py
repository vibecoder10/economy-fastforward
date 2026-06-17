"""Airtable API client for Idea Concepts, Ideas (legacy), Script, and Images tables."""

import os
from pyairtable import Api, Table
from typing import Optional, Any
from orchestrator.pipeline_constants import (
    Models, Statuses, IdeaFields, ScriptFields, ImageFields,
    CompetitorVideoFields, CompetitorChannelFields, OsirisLearningFields,
    TitleInsightFields,
)


# ---------------------------------------------------------------------------
# Field value normalization for style/model overrides
# ---------------------------------------------------------------------------

# Airtable Multiple Select display names → internal model IDs
# Multiple Select returns array like ["Nano Banana"], we need "nano-banana-2"
AIRTABLE_MODEL_NAME_MAP: dict[str, str] = {
    Models.IMAGE_ZIMAGE: Models.IMAGE_ZIMAGE,
    "Nano Banana": Models.IMAGE_SCENE,
    Models.IMAGE_SCENE: Models.IMAGE_SCENE,
}

# Valid visual styles (maps to visual_profiles module names)
VALID_VISUAL_STYLES: set[str] = {
    "neutral_v1",              # Default (style-agnostic; channel look injected)
    "cinematic_illustration",  # Power Doctrine look (opt-in preset)
    "holographic_hud",
    "cinematic_dossier",
    "clay_mannequin",
}
DEFAULT_VISUAL_STYLE = "neutral_v1"

# Default model for video/scene images (z-image), thumbnails use nano-banana-2
DEFAULT_IMAGE_MODEL = Models.IMAGE_SCENE


def get_image_model_override(record: dict) -> str:
    """Extract image model override from an Airtable record.

    Handles both old text format ("z-image") and new Multiple Select
    format (["z-image"] or ["Nano Banana"]).

    Args:
        record: Airtable record dict with fields

    Returns:
        Normalized model ID (e.g. "z-image", "nano-banana-2") or empty string
        if no valid override is set.
    """
    raw_value = record.get(IdeaFields.IMAGE_MODEL_OVERRIDE)

    if not raw_value:
        return DEFAULT_IMAGE_MODEL

    # Handle Multiple Select format: ["z-image"] or ["Nano Banana"]
    if isinstance(raw_value, list):
        if len(raw_value) == 0:
            return DEFAULT_IMAGE_MODEL
        raw_value = raw_value[0]  # Take first selection

    # Normalize to string and clean
    model_name = str(raw_value).strip()
    if not model_name:
        return DEFAULT_IMAGE_MODEL

    # Map display name to internal ID
    normalized = AIRTABLE_MODEL_NAME_MAP.get(model_name)
    if normalized:
        return normalized

    # Try lowercase match as fallback
    normalized = AIRTABLE_MODEL_NAME_MAP.get(model_name.lower())
    if normalized:
        return normalized

    # Unknown model - log warning and return empty (use default)
    print(f"    ⚠️ Unknown image model override '{model_name}', ignoring")
    return DEFAULT_IMAGE_MODEL


def get_visual_style(record: dict) -> str:
    """Extract visual style from an Airtable record.

    Visual Style is a Single Select field that maps to visual profile names.
    Single Select returns a plain string, not an array.

    Args:
        record: Airtable record dict with fields

    Returns:
        Visual style profile ID (e.g. "cinematic_illustration") or default if
        not set or invalid.
    """
    raw_value = record.get(IdeaFields.VISUAL_STYLE)

    if not raw_value:
        return DEFAULT_VISUAL_STYLE

    # Single Select returns string directly, but handle array just in case
    if isinstance(raw_value, list):
        if len(raw_value) == 0:
            return DEFAULT_VISUAL_STYLE
        raw_value = raw_value[0]

    style_name = str(raw_value).strip().lower().replace(" ", "_")

    if not style_name:
        return DEFAULT_VISUAL_STYLE

    if style_name in VALID_VISUAL_STYLES:
        return style_name

    # Unknown style - log warning and return default
    print(f"    ⚠️ Unknown visual style '{raw_value}', using default '{DEFAULT_VISUAL_STYLE}'")
    return DEFAULT_VISUAL_STYLE


class AirtableClient:
    """Client for Airtable API operations.

    === IDEA CONCEPTS FIELD AUDIT (2026-02-15) ===

    ACTIVE fields (written/read by the pipeline):
      Core (always written on create):
        - Status            : Single Select  — set by create_idea, update_idea_status
        - Video Title       : Text           — from viral_title / headline
        - Hook Script       : Text           — from hook / executive_hook
        - Past Context      : Text           — from narrative_logic.past_context
        - Present Parallel  : Text           — from narrative_logic.present_parallel
        - Future Prediction : Text           — from narrative_logic.future_prediction
        - Thumbnail Prompt  : Text           — from thumbnail_visual
        - Writer Guidance   : Text           — from writer_guidance / thesis
        - Original DNA      : Long Text JSON — full source data snapshot
        - Source            : Text           — origin module name

      Rich schema (written by discovery + research):
        - Framework Angle   : Single Select  — inferred by discovery/research (10 values)
        - Headline          : Text           — editorial headline from source/research
        - Timeliness Score  : Number 1-10    — from estimated_appeal (discovery)
        - Audience Fit Score: Number 1-10    — from appeal_breakdown.emotional_trigger
        - Content Gap Score : Number 1-10    — from appeal_breakdown.hidden_system
        - Source URLs       : Long Text      — bibliography from research
        - Executive Hook    : Long Text      — 15-second hook from research
        - Thesis            : Long Text      — core argument from research
        - Date Surfaced     : Date           — when idea was discovered
        - Research Payload  : Long Text JSON — full research_payload from research_agent
        - Thematic Framework: Long Text      — themes extracted during research

      Optional (may be set by specific sources):
        - Reference URL     : URL            — from url_analysis source
        - Idea Reasoning    : Text           — from modeled_from (format library)
        - Source Views      : Number         — from trending source
        - Source Channel    : Text           — from trending source

    LEGACY / UNUSED fields (exist in Airtable, not actively written):
        - Monetization Risk : Single Select  — defined in setup_airtable_fields.py
                              but never populated by any pipeline code.
                              Candidate for manual editorial use or removal.

    Style overrides (written via Slack !style commands):
        - Image Style Override    : Long Text       — custom instructions for image prompt prefix
        - Thumbnail Style Override: Long Text       — custom instructions for thumbnail template
        - Image Model Override    : Multiple Select — hot-swap scene image model (options: z-image, Nano Banana)
        - Visual Style            : Single Select   — visual profile (options: neutral_v1, cinematic_illustration, holographic_hud, cinematic_dossier, clay_mannequin)

    Pipeline-only fields (written by later stages, not discovery/research):
        - Script            : Long Text      — written by brief_translator
        - Scene File Path   : Text           — written by pipeline
        - Accent Color      : Text           — written by pipeline
        - Video ID          : Text           — written by pipeline
        - Scene Count       : Number         — written by pipeline
        - Validation Status : Text           — written by pipeline
        - Drive Folder ID   : Text           — Google Drive folder ID, saved by script bot

    DO NOT DELETE any fields yet — this audit is for documentation only.
    ===================================================================
    """

    # Table IDs from the n8n workflow
    DEFAULT_BASE_ID = "appCIcC58YSTwK3CE"
    IDEAS_TABLE_ID = "tblrAsJglokZSkC8m"          # Legacy alias (same as Idea Concepts)
    SCRIPT_TABLE_ID = "tbluGSepeZNgb0NxG"
    IMAGES_TABLE_ID = "tbl3luJ0zsWu0MYYz"

    # Idea Concepts — single source of truth for ALL new ideas
    IDEA_CONCEPTS_TABLE_ID = "tblrAsJglokZSkC8m"  # Hardcoded default

    # Competitor Channels — tracks competitor YouTube channels for scraping
    COMPETITOR_CHANNELS_TABLE_ID = "tblXXXXXXXXXXXXXX"  # Set in .env after table creation

    # Competitor Videos — Osiris training data (all scraped videos, not just winners)
    COMPETITOR_VIDEOS_TABLE_ID = "tblXXXXXXXXXXXXXX"  # Set in .env after table creation

    # Osiris Learnings — persists learned patterns from performance analysis
    OSIRIS_LEARNINGS_TABLE_ID = "tblXXXXXXXXXXXXXX"  # Set in .env after table creation

    def __init__(self, api_key: Optional[str] = None, base_id: Optional[str] = None):
        self.api_key = api_key or os.getenv("AIRTABLE_API_KEY")
        if not self.api_key:
            raise ValueError("AIRTABLE_API_KEY not found in environment")

        self.base_id = base_id or os.getenv("AIRTABLE_BASE_ID", self.DEFAULT_BASE_ID)
        self.api = Api(self.api_key)

        # Idea Concepts table ID — env override or hardcoded default
        self.IDEA_CONCEPTS_TABLE_ID = os.getenv(
            "AIRTABLE_IDEA_CONCEPTS_TABLE_ID",
            self.__class__.IDEA_CONCEPTS_TABLE_ID,  # tblrAsJglokZSkC8m
        )

        # Initialize table references
        self._ideas_table = None
        self._idea_concepts_table = None
        self._script_table = None
        self._images_table = None
        self._competitor_channels_table = None
        self._competitor_videos_table = None
        self._osiris_learnings_table = None
        self._title_insights_table = None
        self._title_tests_table = None

    @property
    def idea_concepts_table(self) -> Table:
        """Get the Idea Concepts table (single source of truth for new ideas)."""
        if self._idea_concepts_table is None:
            self._idea_concepts_table = self.api.table(
                self.base_id, self.IDEA_CONCEPTS_TABLE_ID
            )
        return self._idea_concepts_table

    @property
    def ideas_table(self) -> Table:
        """Get the legacy Ideas table (preserved as archive, no new writes)."""
        if self._ideas_table is None:
            self._ideas_table = self.api.table(self.base_id, self.IDEAS_TABLE_ID)
        return self._ideas_table
    
    @property
    def script_table(self) -> Table:
        """Get the Script table."""
        if self._script_table is None:
            self._script_table = self.api.table(self.base_id, self.SCRIPT_TABLE_ID)
        return self._script_table
    
    @property
    def images_table(self) -> Table:
        """Get the Images table."""
        if self._images_table is None:
            self._images_table = self.api.table(self.base_id, self.IMAGES_TABLE_ID)
        return self._images_table

    @property
    def competitor_channels_table(self) -> Table:
        """Get the Competitor Channels table."""
        if self._competitor_channels_table is None:
            table_id = os.getenv(
                "AIRTABLE_COMPETITOR_CHANNELS_TABLE_ID",
                self.COMPETITOR_CHANNELS_TABLE_ID,
            )
            self._competitor_channels_table = self.api.table(self.base_id, table_id)
        return self._competitor_channels_table

    @staticmethod
    def _extract_bad_field(error_msg: str) -> Optional[str]:
        """Extract the unknown field name from an Airtable error message."""
        import re
        # Try UNKNOWN_FIELD_NAME style: ...UNKNOWN_FIELD_NAME..."FieldName"...
        for delimiter in ("UNKNOWN_FIELD_NAME", "Unknown field name"):
            if delimiter in error_msg:
                tail = error_msg.split(delimiter)[-1]
                m = re.search(r'"([^"]+)"', tail)
                if m:
                    return m.group(1)
        # Fallback: look for any quoted field name after "field"
        m = re.search(r'field[^"]*"([^"]+)"', error_msg, re.IGNORECASE)
        return m.group(1) if m else None

    # ==================== IDEA CONCEPTS TABLE (new unified entry) ===========

    def get_ideas_by_status(self, status: str, limit: int = 1) -> list[dict]:
        """Get ideas with the specified status from Idea Concepts table."""
        records = self.idea_concepts_table.all(
            formula=f'{{Status}} = "{status}"',
            max_records=limit,
        )
        return [{"id": r["id"], **r["fields"]} for r in records]

    def get_ideas_ready_for_scripting(self, limit: int = 1) -> list[dict]:
        """Get ideas with status 'Ready For Scripting'."""
        return self.get_ideas_by_status(Statuses.READY_SCRIPTING, limit)

    def get_ideas_ready_for_visuals(self, limit: int = 1) -> list[dict]:
        """Get ideas with status 'Ready For Visuals'."""
        return self.get_ideas_by_status("Ready For Visuals", limit)

    def get_all_ideas(self) -> list[dict]:
        """Get all ideas from the Idea Concepts table."""
        records = self.idea_concepts_table.all(sort=["Status"])
        return [{"id": r["id"], **r["fields"]} for r in records]

    def get_idea(self, record_id: str) -> Optional[dict]:
        """Get a single idea by record ID."""
        try:
            r = self.idea_concepts_table.get(record_id)
            return {"id": r["id"], **r["fields"]}
        except Exception:
            return None

    def create_idea(self, idea_data: dict, source: str = "url_analysis") -> dict:
        """Create a new idea record in the Idea Concepts table.

        All new ideas are written to Idea Concepts (single source of truth).
        The legacy Ideas table is preserved as archive but receives no new writes.

        Args:
            idea_data: Dict with idea fields (viral_title, hook_script, etc.)
            source: Origin of this idea — one of:
                    "url_analysis", "trending", "format_library",
                    "research_agent", "discovery_scanner"
        """
        # Core fields (always present in Airtable)
        core_fields = {
            IdeaFields.STATUS: Statuses.IDEA_LOGGED,
            IdeaFields.VIDEO_TITLE: idea_data.get("viral_title", idea_data.get(IdeaFields.VIDEO_TITLE, "")),
            IdeaFields.HOOK_SCRIPT: idea_data.get("hook_script", idea_data.get(IdeaFields.HOOK_SCRIPT, "")),
            IdeaFields.PAST_CONTEXT: idea_data.get("narrative_logic", {}).get("past_context", idea_data.get(IdeaFields.PAST_CONTEXT, "")),
            IdeaFields.PRESENT_PARALLEL: idea_data.get("narrative_logic", {}).get("present_parallel", idea_data.get(IdeaFields.PRESENT_PARALLEL, "")),
            IdeaFields.FUTURE_PREDICTION: idea_data.get("narrative_logic", {}).get("future_prediction", idea_data.get(IdeaFields.FUTURE_PREDICTION, "")),
            IdeaFields.THUMBNAIL_PROMPT: idea_data.get("thumbnail_visual", idea_data.get(IdeaFields.THUMBNAIL_PROMPT, "")),
            IdeaFields.WRITER_GUIDANCE: idea_data.get("writer_guidance", idea_data.get(IdeaFields.WRITER_GUIDANCE, "")),
            IdeaFields.ORIGINAL_DNA: idea_data.get("original_dna", idea_data.get(IdeaFields.ORIGINAL_DNA, "")),
            IdeaFields.SOURCE: source,
        }

        # Optional fields (may not exist in Airtable yet)
        optional_fields = {}
        if idea_data.get("reference_url") or idea_data.get(IdeaFields.REFERENCE_URL):
            optional_fields[IdeaFields.REFERENCE_URL] = idea_data.get("reference_url", idea_data.get(IdeaFields.REFERENCE_URL, ""))
        if idea_data.get("modeled_from"):
            optional_fields[IdeaFields.IDEA_REASONING] = idea_data.get("modeled_from")
        if idea_data.get("source_views"):
            optional_fields[IdeaFields.SOURCE_VIEWS] = idea_data.get("source_views")
        if idea_data.get("source_channel"):
            optional_fields[IdeaFields.SOURCE_CHANNEL] = idea_data.get("source_channel")

        # Rich schema fields (added by setup_airtable_fields.py)
        rich_field_keys = [
            IdeaFields.FRAMEWORK_ANGLE, IdeaFields.HEADLINE, IdeaFields.TIMELINESS_SCORE,
            IdeaFields.AUDIENCE_FIT_SCORE, IdeaFields.CONTENT_GAP_SCORE, "Monetization Risk",
            IdeaFields.SOURCE_URLS, IdeaFields.EXECUTIVE_HOOK, IdeaFields.THESIS, IdeaFields.DATE_SURFACED,
            IdeaFields.RESEARCH_PAYLOAD, IdeaFields.THEMATIC_FRAMEWORK, "Thumbnail Text",
            "Title Candidates",
        ]
        for key in rich_field_keys:
            if key in idea_data and idea_data[key]:
                optional_fields[key] = idea_data[key]

        # Also accept pipeline_writer fields passed directly in idea_data
        pipeline_keys = [
            IdeaFields.SCRIPT, IdeaFields.SCENE_FILE_PATH, IdeaFields.ACCENT_COLOR,
            "Video ID", "Scene Count", "Validation Status",
        ]
        for key in pipeline_keys:
            if key in idea_data:
                optional_fields[key] = idea_data[key]

        all_fields = {**core_fields, **optional_fields}

        # Try with all fields first
        try:
            record = self.idea_concepts_table.create(all_fields, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            error_msg = str(e)
            if "UNKNOWN_FIELD_NAME" not in error_msg and "Unknown field name" not in error_msg:
                raise

            import re
            bad_field = self._extract_bad_field(error_msg)
            dropped_fields = set()

            # Retry by dropping unknown fields one at a time
            remaining = dict(all_fields)
            max_retries = len(all_fields)  # absolute upper bound
            for _attempt in range(max_retries):
                if bad_field and bad_field in remaining:
                    print(f"    ⚠️ Field '{bad_field}' not in Airtable, dropping it")
                    del remaining[bad_field]
                    dropped_fields.add(bad_field)
                elif not dropped_fields:
                    # Can't identify the bad field — create with core fields first,
                    # then update with optional fields individually so we don't lose
                    # all rich data at once.
                    print(f"    ⚠️ Can't identify bad field, creating with core fields then updating rich fields")
                    record = self.idea_concepts_table.create(core_fields, typecast=True)
                    record_id = record["id"]
                    if optional_fields:
                        self._apply_fields_individually(record_id, optional_fields)
                    updated = self.idea_concepts_table.get(record_id)
                    return {"id": updated["id"], **updated["fields"]}
                else:
                    break  # nothing left to drop

                try:
                    record = self.idea_concepts_table.create(remaining, typecast=True)
                    if dropped_fields:
                        print(f"    ⚠️ Saved without fields: {dropped_fields}")
                    return {"id": record["id"], **record["fields"]}
                except Exception as retry_err:
                    error_msg = str(retry_err)
                    if ("UNKNOWN_FIELD_NAME" not in error_msg
                            and "Unknown field name" not in error_msg):
                        raise
                    bad_field = self._extract_bad_field(error_msg)

            # Final fallback: only Status + Video Title (guaranteed Airtable fields)
            print(f"    ⚠️ Multiple fields missing, saving minimal record")
            minimal = {
                IdeaFields.STATUS: core_fields.get(IdeaFields.STATUS, Statuses.IDEA_LOGGED),
                IdeaFields.VIDEO_TITLE: core_fields.get(IdeaFields.VIDEO_TITLE, ""),
            }
            record = self.idea_concepts_table.create(minimal, typecast=True)
            return {"id": record["id"], **record["fields"]}

    def find_idea_by_title(self, title: str) -> Optional[dict]:
        """Find an idea by title using fuzzy matching.

        Tries exact match first, then falls back to case-insensitive
        substring matching across all records.

        Returns:
            Matching idea record, or None if not found.
        """
        from pyairtable.formulas import match

        # Try exact match first
        try:
            records = self.idea_concepts_table.all(
                formula=match({"Video Title": title}),
                max_records=1,
            )
            if records:
                r = records[0]
                return {"id": r["id"], **r["fields"]}
        except Exception:
            pass

        # Fallback: fetch all and do case-insensitive substring match
        all_records = self.idea_concepts_table.all()
        search = title.strip().lower()
        best_match = None
        for r in all_records:
            record_title = r["fields"].get(IdeaFields.VIDEO_TITLE, "")
            if not record_title:
                continue
            if record_title.strip().lower() == search:
                return {"id": r["id"], **r["fields"]}
            if search in record_title.strip().lower() or record_title.strip().lower() in search:
                best_match = {"id": r["id"], **r["fields"]}
        return best_match

    def update_idea_status(self, record_id: str, status: str) -> dict:
        """Update the status of an idea in the Idea Concepts table."""
        record = self.idea_concepts_table.update(record_id, {"Status": status}, typecast=True)
        return {"id": record["id"], **record["fields"]}

    def update_idea_field(self, record_id: str, field_name: str, value) -> dict:
        """Update a single field on an idea record."""
        record = self.idea_concepts_table.update(record_id, {field_name: value})
        return {"id": record["id"], **record["fields"]}

    def _apply_fields_individually(self, record_id: str, fields: dict):
        """Best-effort update: try each field individually so one bad field
        doesn't block the others from being saved."""
        for key, value in fields.items():
            try:
                self.idea_concepts_table.update(record_id, {key: value}, typecast=True)
            except Exception as field_err:
                print(f"    ⚠️ Field '{key}' could not be written: {str(field_err)[:80]}")

    def update_idea_fields(self, record_id: str, fields: dict) -> dict:
        """Update multiple fields on an idea record.

        Gracefully drops unknown fields instead of failing the whole update.
        """
        print(f"[DEBUG] update_idea_fields called: record_id={record_id}, fields={list(fields.keys())}")
        try:
            record = self.idea_concepts_table.update(record_id, fields, typecast=True)
            print(f"[DEBUG] update_idea_fields SUCCESS: wrote {list(fields.keys())}")
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            error_msg = str(e)
            print(f"[DEBUG] update_idea_fields EXCEPTION: {error_msg[:200]}")
            if "UNKNOWN_FIELD_NAME" not in error_msg and "Unknown field name" not in error_msg:
                raise

            # Retry by dropping unknown fields one at a time
            remaining = dict(fields)
            max_retries = len(fields)
            for _ in range(max_retries):
                bad_field = self._extract_bad_field(error_msg)
                if bad_field and bad_field in remaining:
                    print(f"    ⚠️ Field '{bad_field}' not in Airtable, DROPPING IT")
                    del remaining[bad_field]
                else:
                    # Can't identify the bad field — try each field individually
                    # so we save as many as possible instead of losing them all.
                    print(f"    ⚠️ Can't identify bad field, updating fields individually")
                    self._apply_fields_individually(record_id, remaining)
                    break
                if not remaining:
                    return {"id": record_id}
                try:
                    record = self.idea_concepts_table.update(record_id, remaining, typecast=True)
                    return {"id": record["id"], **record["fields"]}
                except Exception as retry_err:
                    error_msg = str(retry_err)
                    if "UNKNOWN_FIELD_NAME" not in error_msg and "Unknown field name" not in error_msg:
                        raise
            return {"id": record_id}

    def update_idea_thumbnail(self, record_id: str, thumbnail_url: str) -> dict:
        """Update the thumbnail URL of an idea."""
        # Try different field names and formats
        field_attempts = [
            # Attachment field format (array of objects with url)
            ("Thumbnail", [{"url": thumbnail_url}]),
            # Plain URL field formats
            ("Thumbnail URL", thumbnail_url),
            ("Thumbnail", thumbnail_url),
        ]

        for field_name, field_value in field_attempts:
            try:
                record = self.idea_concepts_table.update(record_id, {field_name: field_value})
                print(f"    ✅ Saved thumbnail to '{field_name}' field")
                return {"id": record["id"], **record["fields"]}
            except Exception as e:
                continue  # Try next format

        print(f"    Note: Could not save thumbnail URL to Airtable (tried multiple field names)")
        return {"id": record_id}

    def update_idea_curiosity_structure(
        self,
        record_id: str,
        structure: str,
        confidence: int,
        thumbnail_text: str = "",
        thumbnail_approach: str = "from_gap",
    ) -> dict:
        """Update curiosity gap metadata for an idea.

        Args:
            record_id: Airtable record ID
            structure: Curiosity structure name (e.g., "hidden_flaw")
            confidence: Structure confidence score (0-100)
            thumbnail_text: Generated thumbnail text (optional)
            thumbnail_approach: "from_gap" or "from_hook"

        Returns:
            Updated Airtable record
        """
        fields = {
            IdeaFields.CURIOSITY_STRUCTURE: structure,
            IdeaFields.STRUCTURE_CONFIDENCE: confidence,
            IdeaFields.THUMBNAIL_APPROACH: thumbnail_approach,
        }
        if thumbnail_text:
            fields[IdeaFields.THUMBNAIL_TEXT] = thumbnail_text

        record = self.idea_concepts_table.update(record_id, fields, typecast=True)
        return {"id": record["id"], **record["fields"]}

    # ==================== COMPETITOR CHANNELS TABLE ====================

    def get_active_competitor_channels(self) -> list[dict]:
        """Get all active competitor channels for scraping.

        Returns:
            List of channel records with fields: Channel Name, Channel URL, Category, etc.
        """
        records = self.competitor_channels_table.all(
            formula="{Active} = TRUE()",
        )
        return [{"id": r["id"], **r["fields"]} for r in records]

    def update_channel_last_scraped(self, record_id: str) -> dict:
        """Update the Last Scraped date for a channel.

        Args:
            record_id: Airtable record ID for the channel

        Returns:
            Updated record dict
        """
        from datetime import date

        record = self.competitor_channels_table.update(
            record_id,
            {"Last Scraped": date.today().isoformat()},
            typecast=True,
        )
        return {"id": record["id"], **record["fields"]}

    # ==================== COMPETITOR VIDEOS TABLE (Osiris) ====================

    @property
    def competitor_videos_table(self) -> Table:
        """Get the Competitor Videos table (Osiris training data)."""
        if self._competitor_videos_table is None:
            table_id = os.getenv(
                "AIRTABLE_COMPETITOR_VIDEOS_TABLE_ID",
                self.COMPETITOR_VIDEOS_TABLE_ID,
            )
            self._competitor_videos_table = self.api.table(self.base_id, table_id)
        return self._competitor_videos_table

    def get_all_competitor_video_ids(self) -> set[str]:
        """Get all video IDs from Competitor Videos table for deduplication.

        Returns:
            Set of YouTube video IDs already in the table.
        """
        try:
            records = self.competitor_videos_table.all(
                fields=["Video ID"],
            )
            return {r["fields"].get("Video ID") for r in records if r["fields"].get("Video ID")}
        except Exception as e:
            print(f"    ⚠️ Could not fetch existing video IDs: {e}")
            return set()

    def create_competitor_video(self, video_data: dict) -> dict:
        """Create a new competitor video record in the Osiris training table.

        Args:
            video_data: Dict with video fields from Apify scrape + VPH calculation:
                - video_id: YouTube video ID (required, used for deduplication)
                - title: Video title
                - url: Full YouTube URL
                - channel: Channel name
                - channel_url: Channel URL
                - views: View count at scrape time
                - vph: Views per hour
                - hours_old: Age in hours
                - published_at: ISO date string

        Returns:
            Created record dict with id + fields
        """
        from datetime import date

        fields = {
            CompetitorVideoFields.VIDEO_ID: video_data.get("video_id", ""),
            CompetitorVideoFields.TITLE: video_data.get("title", ""),
            CompetitorVideoFields.URL: video_data.get("url", ""),
            CompetitorVideoFields.CHANNEL: video_data.get("channel", ""),
            CompetitorVideoFields.CHANNEL_URL: video_data.get("channel_url", ""),
            CompetitorVideoFields.VIEWS: video_data.get("views", 0),
            CompetitorVideoFields.VPH: round(video_data.get("vph", 0), 1),
            CompetitorVideoFields.HOURS_OLD: round(video_data.get("hours_old", 0), 1),
            CompetitorVideoFields.PUBLISHED_DATE: video_data.get("published_at", "")[:10] if video_data.get("published_at") else "",
            CompetitorVideoFields.SCRAPE_DATE: date.today().isoformat(),
            CompetitorVideoFields.MODELED: False,
        }

        try:
            record = self.competitor_videos_table.create(fields, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            error_msg = str(e)
            if "UNKNOWN_FIELD_NAME" not in error_msg:
                raise
            # Graceful degradation: drop unknown field and retry
            bad_field = self._extract_bad_field(error_msg)
            if bad_field and bad_field in fields:
                print(f"    ⚠️ Field '{bad_field}' not in Competitor Videos table, dropping it")
                del fields[bad_field]
                record = self.competitor_videos_table.create(fields, typecast=True)
                return {"id": record["id"], **record["fields"]}
            raise

    def batch_create_competitor_videos(self, videos: list[dict]) -> list[dict]:
        """Batch create competitor video records (more efficient than individual creates).

        Uses Airtable batch API for efficiency (up to 10 records per call).

        Args:
            videos: List of video data dicts (same format as create_competitor_video)

        Returns:
            List of created record dicts
        """
        from datetime import date

        if not videos:
            return []

        # Build field dicts for all videos
        records_to_create = []
        today = date.today().isoformat()

        for video_data in videos:
            fields = {
                CompetitorVideoFields.VIDEO_ID: video_data.get("video_id", ""),
                CompetitorVideoFields.TITLE: video_data.get("title", ""),
                CompetitorVideoFields.URL: video_data.get("url", ""),
                CompetitorVideoFields.CHANNEL: video_data.get("channel", ""),
                CompetitorVideoFields.CHANNEL_URL: video_data.get("channel_url", ""),
                CompetitorVideoFields.VIEWS: video_data.get("views", 0),
                CompetitorVideoFields.VPH: round(video_data.get("vph", 0), 1),
                CompetitorVideoFields.HOURS_OLD: round(video_data.get("hours_old", 0), 1),
                CompetitorVideoFields.PUBLISHED_DATE: video_data.get("published_at", "")[:10] if video_data.get("published_at") else "",
                CompetitorVideoFields.SCRAPE_DATE: today,
                CompetitorVideoFields.MODELED: False,
            }
            records_to_create.append({"fields": fields})

        # Use batch_create (handles chunking into groups of 10)
        try:
            created = self.competitor_videos_table.batch_create(
                [r["fields"] for r in records_to_create],
                typecast=True,
            )
            return [{"id": r["id"], **r["fields"]} for r in created]
        except Exception as e:
            error_msg = str(e)
            if "UNKNOWN_FIELD_NAME" not in error_msg:
                raise
            # Fallback to individual creates with graceful degradation
            print(f"    ⚠️ Batch create failed, falling back to individual creates")
            results = []
            for video_data in videos:
                try:
                    result = self.create_competitor_video(video_data)
                    results.append(result)
                except Exception as ind_err:
                    print(f"    ⚠️ Failed to create video {video_data.get('video_id')}: {ind_err}")
            return results

    def get_competitor_videos_with_metrics(
        self,
        min_vph: float = 0,
        min_views: int = 0,
        limit: int = 500,
    ) -> list[dict]:
        """Get competitor videos with performance metrics for analysis.

        Args:
            min_vph: Minimum VPH filter (default 0 = all)
            min_views: Minimum view count filter (default 0 = all)
            limit: Max records to return (default 500)

        Returns:
            List of video dicts with fields: Title, VPH, Views, Hours Old,
            Published Date, Channel, URL
        """
        try:
            # Build formula for filtering
            conditions = []
            if min_vph > 0:
                conditions.append(f"{{VPH}} >= {min_vph}")
            if min_views > 0:
                conditions.append(f"{{Views}} >= {min_views}")

            formula = None
            if conditions:
                formula = "AND(" + ", ".join(conditions) + ")"

            records = self.competitor_videos_table.all(
                formula=formula,
                max_records=limit,
                sort=["-VPH"],  # Highest VPH first
                fields=[
                    CompetitorVideoFields.TITLE,
                    CompetitorVideoFields.VPH,
                    CompetitorVideoFields.VIEWS,
                    CompetitorVideoFields.HOURS_OLD,
                    CompetitorVideoFields.PUBLISHED_DATE,
                    CompetitorVideoFields.CHANNEL,
                    CompetitorVideoFields.URL,
                ],
            )
            return [r["fields"] for r in records if r["fields"].get(CompetitorVideoFields.VPH)]
        except Exception as e:
            print(f"    ⚠️ Could not fetch competitor videos: {e}")
            return []

    def update_competitor_curiosity_analysis(
        self,
        record_id: str,
        structure: str,
        structure_confidence: int,
        thumbnail_style_json: Optional[str] = None,
        yin_yang_approach: Optional[str] = None,
        yin_yang_text: Optional[str] = None,
    ) -> bool:
        """Update competitor video with curiosity gap analysis results.

        Args:
            record_id: Airtable record ID
            structure: CuriosityStructure value (e.g., "hidden_flaw")
            structure_confidence: 0-100 confidence score
            thumbnail_style_json: JSON string of thumbnail analysis (optional)
            yin_yang_approach: "from_hook" or "from_gap" (optional)
            yin_yang_text: Extracted thumbnail text (optional)

        Returns:
            True if update succeeded
        """
        from datetime import datetime

        fields = {
            CompetitorVideoFields.CURIOSITY_STRUCTURE: structure,
            CompetitorVideoFields.STRUCTURE_CONFIDENCE: structure_confidence,
            CompetitorVideoFields.ANALYSIS_DATE: datetime.now().strftime("%Y-%m-%d"),
        }

        if thumbnail_style_json:
            fields[CompetitorVideoFields.THUMBNAIL_STYLE_JSON] = thumbnail_style_json

        if yin_yang_approach:
            fields[CompetitorVideoFields.YIN_YANG_APPROACH] = yin_yang_approach

        if yin_yang_text:
            fields[CompetitorVideoFields.YIN_YANG_TEXT] = yin_yang_text

        try:
            self.competitor_videos_table.update(record_id, fields)
            return True
        except Exception as e:
            print(f"Failed to update competitor curiosity analysis: {e}")
            return False

    def get_competitor_videos_by_channel(
        self,
        channel_name: str,
        limit: int = 20,
    ) -> list[dict]:
        """Get recent competitor videos for a channel.

        Args:
            channel_name: Channel name (e.g., "CaspianReport")
            limit: Maximum records to return

        Returns:
            List of Airtable records
        """
        # Match by channel name - existing pattern uses Channel field
        formula = f"{{Channel}} = '{channel_name}'"

        try:
            records = self.competitor_videos_table.all(
                formula=formula,
                sort=["-VPH"],
                max_records=limit,
            )
            return records
        except Exception as e:
            print(f"Failed to get competitor videos by channel: {e}")
            return []

    def get_unanalyzed_competitor_videos(
        self,
        min_vph: float = 50,
        limit: int = 100,
    ) -> list[dict]:
        """Get competitor videos that haven't been analyzed for curiosity gap.

        Args:
            min_vph: Minimum VPH threshold
            limit: Maximum records to return

        Returns:
            List of Airtable records without curiosity analysis
        """
        # Videos with VPH >= threshold AND no Curiosity Structure set
        formula = f"AND({{VPH}} >= {min_vph}, {{Curiosity Structure}} = '')"

        try:
            records = self.competitor_videos_table.all(
                formula=formula,
                sort=["-VPH"],
                max_records=limit,
            )
            return records
        except Exception as e:
            print(f"Failed to get unanalyzed competitor videos: {e}")
            return []

    # ==================== OSIRIS LEARNINGS TABLE ====================

    @property
    def osiris_learnings_table(self) -> Table:
        """Get the Osiris Learnings table (persisted patterns from performance analysis)."""
        if self._osiris_learnings_table is None:
            table_id = os.getenv(
                "AIRTABLE_OSIRIS_LEARNINGS_TABLE_ID",
                self.OSIRIS_LEARNINGS_TABLE_ID,
            )
            self._osiris_learnings_table = self.api.table(self.base_id, table_id)
        return self._osiris_learnings_table

    def get_all_learnings(self, category: str = None, active_only: bool = True) -> list[dict]:
        """Get learnings from Osiris Learnings table.

        Args:
            category: Filter by category (title, hook, thumbnail, retention, framework)
            active_only: Only return active learnings (default True)

        Returns:
            List of learning records with fields
        """
        try:
            formula_parts = []
            if active_only:
                formula_parts.append("{Active} = TRUE()")
            if category:
                formula_parts.append(f'{{Category}} = "{category}"')

            formula = None
            if len(formula_parts) == 1:
                formula = formula_parts[0]
            elif len(formula_parts) > 1:
                formula = f"AND({', '.join(formula_parts)})"

            records = self.osiris_learnings_table.all(
                formula=formula,
                sort=["-Confidence"],  # Sort by confidence descending
            )
            return [{"id": r["id"], **r["fields"]} for r in records]
        except Exception as e:
            print(f"    ⚠️ Could not fetch learnings: {e}")
            return []

    def create_learning(self, learning: dict) -> dict:
        """Create a new learning record in the Osiris Learnings table.

        Args:
            learning: Dict with learning fields:
                - Category: title, hook, thumbnail, retention, framework
                - Pattern: The learned pattern description
                - Confidence: 0-100 based on sample size and consistency
                - Sample Size: Number of videos this pattern is based on
                - Avg CTR: Average CTR for matching videos (optional)
                - Avg Retention: Average retention for matching videos (optional)
                - Source Videos: JSON array of video titles (optional)

        Returns:
            Created record dict
        """
        from datetime import date

        fields = {
            OsirisLearningFields.CATEGORY: learning.get("category", ""),
            OsirisLearningFields.PATTERN: learning.get("pattern", ""),
            OsirisLearningFields.CONFIDENCE: learning.get("confidence", 50),
            OsirisLearningFields.SAMPLE_SIZE: learning.get("sample_size", 1),
            OsirisLearningFields.ACTIVE: True,
            OsirisLearningFields.CREATED: date.today().isoformat(),
            OsirisLearningFields.LAST_UPDATED: date.today().isoformat(),
        }

        # Optional fields
        if learning.get("avg_ctr") is not None:
            fields[OsirisLearningFields.AVG_CTR] = round(learning["avg_ctr"], 2)
        if learning.get("avg_retention") is not None:
            fields[OsirisLearningFields.AVG_RETENTION] = round(learning["avg_retention"], 1)
        if learning.get("source_videos"):
            import json
            fields[OsirisLearningFields.SOURCE_VIDEOS] = json.dumps(learning["source_videos"])

        try:
            record = self.osiris_learnings_table.create(fields, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            error_msg = str(e)
            if "UNKNOWN_FIELD_NAME" not in error_msg:
                raise
            # Graceful degradation: drop unknown field and retry
            bad_field = self._extract_bad_field(error_msg)
            if bad_field and bad_field in fields:
                print(f"    ⚠️ Field '{bad_field}' not in Osiris Learnings table, dropping it")
                del fields[bad_field]
                record = self.osiris_learnings_table.create(fields, typecast=True)
                return {"id": record["id"], **record["fields"]}
            raise

    def update_learning(self, record_id: str, updates: dict) -> dict:
        """Update an existing learning record.

        Args:
            record_id: Airtable record ID
            updates: Dict of fields to update

        Returns:
            Updated record dict
        """
        from datetime import date

        updates["Last Updated"] = date.today().isoformat()
        record = self.osiris_learnings_table.update(record_id, updates, typecast=True)
        return {"id": record["id"], **record["fields"]}

    # ==================== TITLE INSIGHTS TABLE ====================

    @property
    def title_insights_table(self) -> Table:
        """Get the Title Insights table (competitor title pattern analysis)."""
        if self._title_insights_table is None:
            table_id = os.getenv("AIRTABLE_TITLE_INSIGHTS_TABLE_ID", "")
            if not table_id:
                raise ValueError(
                    "AIRTABLE_TITLE_INSIGHTS_TABLE_ID not set. "
                    "Create the Title Insights table in Airtable and add the ID to .env"
                )
            self._title_insights_table = self.api.table(self.base_id, table_id)
        return self._title_insights_table

    def create_title_insight(self, insight: dict) -> dict:
        """Create a new title insight record.

        Args:
            insight: Dict with insight fields:
                - pattern_type: "structural" or "semantic"
                - pattern_name: e.g., "Question Format", "Urgency Hook"
                - description: What the pattern is and why it works
                - example_titles: List of example titles
                - avg_vph: Average VPH of matching videos
                - count: How many videos match
                - confidence: 0-100 confidence score
                - videos_analyzed: Total videos in this analysis run
                - vph_threshold: Min VPH filter used

        Returns:
            Created record dict
        """
        from datetime import date
        import json

        fields = {
            TitleInsightFields.ANALYSIS_DATE: date.today().isoformat(),
            TitleInsightFields.PATTERN_TYPE: insight.get("pattern_type", "structural"),
            TitleInsightFields.PATTERN_NAME: insight.get("pattern_name", ""),
            TitleInsightFields.DESCRIPTION: insight.get("description", ""),
            TitleInsightFields.EXAMPLE_TITLES: json.dumps(insight.get("example_titles", [])),
            TitleInsightFields.AVG_VPH: round(insight.get("avg_vph", 0), 1),
            TitleInsightFields.COUNT: insight.get("count", 0),
            TitleInsightFields.CONFIDENCE: insight.get("confidence", 50),
            TitleInsightFields.VIDEOS_ANALYZED: insight.get("videos_analyzed", 0),
            TitleInsightFields.VPH_THRESHOLD: insight.get("vph_threshold", 0),
        }

        try:
            record = self.title_insights_table.create(fields, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            error_msg = str(e)
            if "UNKNOWN_FIELD_NAME" not in error_msg:
                raise
            # Graceful degradation: drop unknown field and retry
            bad_field = self._extract_bad_field(error_msg)
            if bad_field and bad_field in fields:
                print(f"    ⚠️ Field '{bad_field}' not in Title Insights table, dropping it")
                del fields[bad_field]
                record = self.title_insights_table.create(fields, typecast=True)
                return {"id": record["id"], **record["fields"]}
            raise

    def batch_create_title_insights(self, insights: list[dict]) -> list[dict]:
        """Batch create title insight records.

        Args:
            insights: List of insight dicts with TitleInsightFields keys
                      (pre-formatted by caller, e.g. _persist_insights)

        Returns:
            List of created record dicts
        """
        if not insights:
            return []

        # insights are already formatted with TitleInsightFields keys
        # by the caller (_persist_insights), so pass them directly
        try:
            created = self.title_insights_table.batch_create(insights, typecast=True)
            return [{"id": r["id"], **r["fields"]} for r in created]
        except Exception as e:
            # Fallback to individual creates
            print(f"    ⚠️ Batch create failed, falling back to individual creates: {e}")
            results = []
            for insight in insights:
                try:
                    result = self.title_insights_table.create(insight, typecast=True)
                    results.append({"id": result["id"], **result["fields"]})
                except Exception as ind_err:
                    print(f"    ⚠️ Failed to create insight: {ind_err}")
            return results

    def get_title_insights(self, pattern_type: str = None, limit: int = 100) -> list[dict]:
        """Get title insights from the table.

        Args:
            pattern_type: Filter by "structural" or "semantic" (optional)
            limit: Max records to return

        Returns:
            List of insight records
        """
        try:
            formula = None
            if pattern_type:
                formula = f'{{Pattern Type}} = "{pattern_type}"'

            records = self.title_insights_table.all(
                formula=formula,
                max_records=limit,
                sort=["-Analysis Date", "-Confidence"],
            )
            return [{"id": r["id"], **r["fields"]} for r in records]
        except Exception as e:
            print(f"    ⚠️ Could not fetch title insights: {e}")
            return []

    # ==================== TITLE TESTS TABLE ====================

    @property
    def title_tests_table(self) -> Table:
        """Get the Title Tests table (curiosity gap A/B testing)."""
        if self._title_tests_table is None:
            from orchestrator.pipeline_constants import AIRTABLE_TITLE_TESTS_TABLE_ID
            table_id = AIRTABLE_TITLE_TESTS_TABLE_ID
            if not table_id:
                raise ValueError(
                    "AIRTABLE_TITLE_TESTS_TABLE_ID not set in pipeline_constants.py"
                )
            self._title_tests_table = self.api.table(self.base_id, table_id)
        return self._title_tests_table

    def create_title_test(self, title_test: dict) -> dict:
        """Create a new title test record.

        Args:
            title_test: Dict with TitleTestFields values

        Returns:
            Created record dict
        """
        from orchestrator.pipeline_constants import TitleTestFields

        fields = {
            TitleTestFields.IDEA: title_test.get("idea", ""),
            TitleTestFields.TITLE_TEXT: title_test.get("title_text", ""),
            TitleTestFields.STRUCTURE: title_test.get("structure", ""),
            TitleTestFields.STRUCTURE_CONFIDENCE: title_test.get("structure_confidence", 0),
            TitleTestFields.THUMBNAIL_TEXT: title_test.get("thumbnail_text", ""),
            TitleTestFields.THUMBNAIL_APPROACH: title_test.get("thumbnail_approach", ""),
            TitleTestFields.SOURCE_PATTERNS: title_test.get("source_patterns", ""),
            TitleTestFields.PATTERN_LIBRARY_SNAPSHOT: title_test.get("pattern_library_snapshot", ""),
            TitleTestFields.VIDEO_TITLE: title_test.get("video_title", ""),
        }

        # Remove empty values
        fields = {k: v for k, v in fields.items() if v}

        try:
            record = self.title_tests_table.create(fields, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            print(f"    ⚠️ Failed to create title test: {e}")
            raise

    def get_title_tests_for_idea(self, idea_record_id: str) -> list[dict]:
        """Get all title test variants for an idea.

        Args:
            idea_record_id: Ideas table record ID

        Returns:
            List of title test records
        """
        from orchestrator.pipeline_constants import TitleTestFields

        formula = f"{{Idea}} = '{idea_record_id}'"
        try:
            records = self.title_tests_table.all(formula=formula)
            return [{"id": r["id"], **r["fields"]} for r in records]
        except Exception as e:
            print(f"    ⚠️ Could not fetch title tests: {e}")
            return []

    def update_title_test(self, record_id: str, fields: dict) -> dict:
        """Update a title test record.

        Args:
            record_id: Title test record ID
            fields: Fields to update

        Returns:
            Updated record
        """
        return self.title_tests_table.update(record_id, fields, typecast=True)

    def get_videos_needing_postmortem(self) -> list[dict]:
        """Get uploaded videos that need 48h or 7d post-mortem analysis.

        Returns videos that:
        - Have YouTube Video ID (uploaded)
        - Have Upload Date
        - Are at least 48 hours old
        - Don't have Post-Mortem 48h or Post-Mortem 7d filled

        Returns:
            List of video records needing analysis
        """
        from datetime import datetime, timedelta, timezone

        # Get all uploaded videos
        all_ideas = self.get_all_ideas()
        uploaded = [r for r in all_ideas if r.get(IdeaFields.YOUTUBE_VIDEO_ID)]

        needs_analysis = []
        now = datetime.now(timezone.utc)

        for video in uploaded:
            upload_date_str = video.get("Upload Date")
            if not upload_date_str:
                continue

            try:
                upload_dt = datetime.fromisoformat(upload_date_str.replace("Z", "+00:00"))
                hours_since = (now - upload_dt).total_seconds() / 3600
            except (ValueError, TypeError):
                continue

            # Check if needs 48h analysis
            if hours_since >= 48 and not video.get("Post-Mortem 48h"):
                needs_analysis.append({
                    **video,
                    "_analysis_type": "48h",
                    "_hours_since_upload": hours_since,
                })
            # Check if needs 7d analysis
            elif hours_since >= 168 and not video.get("Post-Mortem 7d"):
                needs_analysis.append({
                    **video,
                    "_analysis_type": "7d",
                    "_hours_since_upload": hours_since,
                })

        return needs_analysis

    # ==================== SCRIPT TABLE ====================
    
    def get_scripts_to_create(self) -> list[dict]:
        """Get script records with status 'Create', ordered by scene number."""
        records = self.script_table.all(
            formula='{Script Status} = "Create"',
            sort=["scene"],
        )
        return [{"id": r["id"], **r["fields"]} for r in records]
    
    def get_scripts_by_title(self, title: str) -> list[dict]:
        """Get all script records for a specific video title, ordered by scene number.

        Tries the standard "Title" field, then falls back to fetching all
        scripts and matching by any title-like field — handles minor title
        mismatches and unexpected field names.
        """
        from pyairtable.formulas import match

        # Try "Title" field (standard field name on Script table)
        try:
            records = self.script_table.all(
                formula=match({"Title": title}),
                sort=["scene"],
            )
            if records:
                return [{"id": r["id"], **r["fields"]} for r in records]
        except Exception:
            pass  # Field may not exist — continue to fallback

        # Fallback: fetch all scripts and match by any title-like field
        # Handles field renames, smart quotes, trailing spaces, etc.
        try:
            all_records = self.script_table.all(sort=["scene"])
        except Exception:
            return []

        if not all_records:
            return []

        # Normalize the search title for comparison
        search_title = title.strip().lower()

        matched = []
        for r in all_records:
            fields = r["fields"]
            # Check every text field that could contain the title
            for field_name in ("Title", "Video Title", "Name"):
                record_title = fields.get(field_name, "")
                if record_title and record_title.strip().lower() == search_title:
                    matched.append({"id": r["id"], **fields})
                    break

        return matched
    
    def create_script_record(
        self,
        scene_number: int,
        scene_text: str,
        title: str,
        voice_id: str = "UgBBYS2sOqTuMpoF3BR0",
        sources: str = "",
        psych_angle: str = "",
    ) -> dict:
        """Create a new script record for a scene."""
        fields = {
            "scene": scene_number,
            ScriptFields.SCENE_TEXT: scene_text,
            ScriptFields.TITLE: title,
            ScriptFields.VOICE_ID: voice_id,
            ScriptFields.SCRIPT_STATUS: ScriptFields.STATUS_CREATE,  # Single select, not array
        }
        # Store full source list on scene 1 for YouTube show notes
        if sources and scene_number == 1:
            fields[ScriptFields.SOURCES] = sources
        if psych_angle:
            fields[ScriptFields.PSYCH_ANGLE] = psych_angle
        try:
            record = self.script_table.create(fields, typecast=True)
        except Exception as e:
            error_msg = str(e)
            if "UNKNOWN_FIELD_NAME" not in error_msg:
                raise
            # Gracefully drop unknown fields and retry
            bad_field = self._extract_bad_field(error_msg)
            if bad_field and bad_field in fields:
                print(f"    ⚠️ {bad_field} field not on Script table — add it in Airtable")
                del fields[bad_field]
                record = self.script_table.create(fields, typecast=True)
            else:
                raise
        return {"id": record["id"], **record["fields"]}
    
    def update_script_record(
        self,
        record_id: str,
        updates: dict[str, Any],
    ) -> dict:
        """Update a script record."""
        record = self.script_table.update(record_id, updates)
        return {"id": record["id"], **record["fields"]}
    
    def mark_script_finished(
        self,
        record_id: str,
        voice_over_url: Optional[str] = None,
    ) -> dict:
        """Mark a script record as finished."""
        updates = {
            ScriptFields.SCRIPT_STATUS: ScriptFields.STATUS_FINISHED,
            ScriptFields.VOICE_STATUS: ImageFields.STATUS_DONE,
        }
        if voice_over_url:
            updates[ScriptFields.VOICE_OVER] = [{"url": voice_over_url}]
        return self.update_script_record(record_id, updates)
    
    # ==================== IMAGES TABLE ====================
    
    def get_pending_images(self) -> list[dict]:
        """Get image records with status 'Pending', ordered by scene and index."""
        records = self.images_table.all(
            formula='{Status} = "Pending"',
            sort=[ImageFields.SCENE, ImageFields.IMAGE_INDEX],
        )
        return [{"id": r["id"], **r["fields"]} for r in records]
    
    def create_concept_record(
        self,
        scene_number: int,
        concept_index: int,
        sentence_text: str,
        image_prompt: str,
        composition: str,
        video_title: str,
        aspect_ratio: str = "16:9",
    ) -> dict:
        """Create an image record from a visual concept expansion.

        Each record represents one visual concept within a scene — a portion
        of the narration paired with a styled image prompt ready for generation.

        Args:
            scene_number: Scene number from Script table
            concept_index: 1-based position within the scene
            sentence_text: Exact narration text this concept covers
            image_prompt: Styled image prompt (built via build_prompt)
            composition: wide / medium / closeup / etc.
            video_title: Title linking to Ideas table
            aspect_ratio: Image aspect ratio

        Returns:
            Created record dict with id + fields
        """
        fields = {
            ImageFields.SCENE: scene_number,
            ImageFields.IMAGE_INDEX: concept_index,
            ImageFields.SENTENCE_TEXT: sentence_text,
            ImageFields.IMAGE_PROMPT: image_prompt,
            ImageFields.SHOT_TYPE: composition,
            ImageFields.VIDEO_TITLE: video_title,
            ImageFields.ASPECT_RATIO: aspect_ratio,
            ImageFields.STATUS: ImageFields.STATUS_PENDING,
            ImageFields.SENTENCE_INDEX: concept_index,
        }
        record = self.images_table.create(fields, typecast=True)
        return {"id": record["id"], **record["fields"]}
    
    def update_image_record(
        self,
        record_id: str,
        image_url: str,
        drive_url: Optional[str] = None,
    ) -> dict:
        """Update an image record with the generated image."""
        updates = {
            ImageFields.IMAGE: [{"url": image_url}],
            ImageFields.STATUS: ImageFields.STATUS_DONE,
        }
        if drive_url:
            updates[ImageFields.DRIVE_IMAGE_URL] = drive_url
        try:
            record = self.images_table.update(record_id, updates, typecast=True)
        except Exception as e:
            # If Drive Image URL field doesn't exist yet, retry without it
            if "UNKNOWN_FIELD_NAME" in str(e) and drive_url:
                del updates[ImageFields.DRIVE_IMAGE_URL]
                record = self.images_table.update(record_id, updates, typecast=True)
            else:
                raise
        return {"id": record["id"], **record["fields"]}

    def update_image_video_url(
        self,
        record_id: str,
        video_url: str,
    ) -> dict:
        """Update an image record with the generated video URL."""
        # Note: 'Video' field based on screenshot, 'Video Status' to Done
        updates = {
            ImageFields.VIDEO: [{"url": video_url}], # Attachment field uses list of dicts
            ImageFields.VIDEO_STATUS: ImageFields.STATUS_DONE,
        }
        record = self.images_table.update(record_id, updates)
        return {"id": record["id"], **record["fields"]}

    def update_image_video_prompt(
        self,
        record_id: str,
        prompt: str,
    ) -> dict:
        """Update an image record with the video motion prompt."""
        updates = {
            ImageFields.VIDEO_PROMPT: prompt,
            ImageFields.VIDEO_STATUS: ImageFields.STATUS_PENDING,
        }
        record = self.images_table.update(record_id, updates)
        return {"id": record["id"], **record["fields"]}

    def update_image_animation_fields(
        self,
        record_id: str,
        shot_type: str = None,
        is_hero_shot: bool = None,
        video_clip_url: str = None,
        animation_status: str = None,
        video_duration: int = None,
    ) -> dict:
        """Update animation-related fields on an image record.

        These fields support the image-to-video animation pipeline.

        Args:
            record_id: Airtable record ID
            shot_type: Scene type (e.g., "ISOMETRIC_DIORAMA", "SPLIT_SCREEN")
            is_hero_shot: Whether this is a hero shot (10s instead of 6s)
            video_clip_url: Direct URL to the video clip on Google Drive
            animation_status: "Pending", "Processing", "Done", "Failed"
            video_duration: Duration in seconds (6 or 10)

        Returns:
            Updated record dict

        Note:
            User must add these fields to Airtable Images table:
            - Shot Type (Single Select)
            - Hero Shot (Checkbox)
            - Video Clip URL (URL)
            - Animation Status (Single Select)
            - Video Duration (Number)
        """
        updates = {}

        if shot_type is not None:
            updates[ImageFields.SHOT_TYPE] = shot_type
        if is_hero_shot is not None:
            updates[ImageFields.HERO_SHOT] = is_hero_shot
        if video_clip_url is not None:
            updates[ImageFields.VIDEO_CLIP_URL] = video_clip_url
        if animation_status is not None:
            updates[ImageFields.ANIMATION_STATUS] = animation_status
        if video_duration is not None:
            updates[ImageFields.VIDEO_DURATION] = video_duration

        if not updates:
            return {"id": record_id}

        try:
            record = self.images_table.update(record_id, updates, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            error_str = str(e)
            if "UNKNOWN_FIELD_NAME" in error_str:
                # Some animation fields might not be added to Airtable yet
                print(f"      ⚠️ Some animation fields missing in Airtable schema: {error_str[:100]}")
                # Try with only the core fields that are more likely to exist
                core_fields = [ImageFields.VIDEO_CLIP_URL]
                core_updates = {k: v for k, v in updates.items() if k in core_fields}
                if core_updates:
                    try:
                        record = self.images_table.update(record_id, core_updates, typecast=True)
                        return {"id": record["id"], **record["fields"]}
                    except Exception:
                        pass
                return {"id": record_id, "warning": "Animation fields not found in Airtable"}
            raise

    def update_image_prompt_fields(
        self,
        record_id: str,
        image_prompt: str = None,
        shot_type: str = None,
    ) -> dict:
        """Update prompt-related fields on an image record.

        Used by prompt_validator to auto-fix issues before image generation.

        Args:
            record_id: Airtable record ID
            image_prompt: Updated prompt text
            shot_type: Camera composition (wide/medium/closeup)

        Returns:
            Updated record dict
        """
        updates = {}
        if image_prompt is not None:
            updates[ImageFields.IMAGE_PROMPT] = image_prompt
        if shot_type is not None:
            updates[ImageFields.SHOT_TYPE] = shot_type

        if not updates:
            return {"id": record_id}

        record = self.images_table.update(record_id, updates, typecast=True)
        return {"id": record["id"], **record["fields"]}

    def get_images_ready_for_video_generation(self, video_title: str) -> list[dict]:
        """Get image records that are Done but missing a Video URL."""
        from pyairtable.formulas import match, AND
        # We want records where:
        # 1. Video Title matches
        # 2. Status is "Done" (Image exists)
        # 3. Video URL is empty
        # Note: AirTable formula for empty field is just checking if it exists
        # But easier to fetch all done images and filter in python if formula is tricky
        # Formula: AND(match Title, match Status Done)
        # We filter for missing Video in python
        
        records = self.images_table.all(
            formula=AND(
                match({ImageFields.VIDEO_TITLE: video_title}),
                match({ImageFields.STATUS: ImageFields.STATUS_DONE}),
            ),
            sort=[ImageFields.SCENE, ImageFields.IMAGE_INDEX],
        )
        # Filter python side for empty video
        # 'Video' is an attachment field, so check if it's empty or None
        return [{"id": r["id"], **r["fields"]} for r in records if not r["fields"].get(ImageFields.VIDEO)]
    
    def get_pending_images_for_video(self, video_title: str) -> list[dict]:
        """Get pending image records for a specific video, ordered by scene and index."""
        from pyairtable.formulas import match, AND
        records = self.images_table.all(
            formula=AND(
                match({ImageFields.VIDEO_TITLE: video_title}),
                match({ImageFields.STATUS: ImageFields.STATUS_PENDING}),
            ),
            sort=[ImageFields.SCENE, ImageFields.IMAGE_INDEX],
        )
        return [{"id": r["id"], **r["fields"]} for r in records]
    
    def get_all_images_for_video(self, video_title: str) -> list[dict]:
        """Get all image records for a specific video."""
        from pyairtable.formulas import match
        records = self.images_table.all(
            formula=match({ImageFields.VIDEO_TITLE: video_title}),
            sort=[ImageFields.SCENE, ImageFields.IMAGE_INDEX],
        )
        return [{"id": r["id"], **r["fields"]} for r in records]

    def update_image_sound_prompt(self, record_id: str, sound_prompt: str) -> dict:
        """Write a sound prompt to an image record."""
        updates = {ImageFields.SOUND_PROMPT: sound_prompt}
        try:
            record = self.images_table.update(record_id, updates, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            if "UNKNOWN_FIELD_NAME" in str(e):
                print(f"      ⚠️ ImageFields.SOUND_PROMPT field not found in Images table — add it in Airtable")
                return {"id": record_id, "warning": "Sound Prompt field missing"}
            raise

    def update_image_sound_effect(
        self,
        record_id: str,
        sound_url: str,
        volume: float = 0.15,
    ) -> dict:
        """Attach a generated sound effect to an image record."""
        updates = {
            ImageFields.SOUND_EFFECT: [{"url": sound_url}],
            ImageFields.SOUND_VOLUME: volume,
        }
        try:
            record = self.images_table.update(record_id, updates, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            error_str = str(e)
            if "UNKNOWN_FIELD_NAME" in error_str:
                # Try fields individually (graceful degradation)
                print(f"      ⚠️ Some sound fields missing, trying individually...")
                for field, value in updates.items():
                    try:
                        self.images_table.update(record_id, {field: value}, typecast=True)
                    except Exception:
                        print(f"      ⚠️ '{field}' field not found in Images table — add it in Airtable")
                return {"id": record_id, "warning": "Some sound fields missing"}
            raise

    def delete_scripts_for_video(self, video_title: str) -> int:
        """Delete all script records for a video title.

        Returns the number of records deleted.
        """
        records = self.get_scripts_by_title(video_title)
        if not records:
            return 0
        record_ids = [r["id"] for r in records]
        self.script_table.batch_delete(record_ids)
        return len(record_ids)

    def delete_images_for_video(self, video_title: str) -> int:
        """Delete all image/concept records for a video title.

        Returns the number of records deleted.
        """
        records = self.get_all_images_for_video(video_title)
        if not records:
            return 0
        record_ids = [r["id"] for r in records]
        self.images_table.batch_delete(record_ids)
        return len(record_ids)

    def update_record(self, table_name: str, record_id: str, fields: dict) -> dict:
        """Generic update for any table record.

        Args:
            table_name: "Ideas", "Idea Concepts", "Script", or "Images"
            record_id: Airtable record ID
            fields: Dict of field names to values

        Returns:
            Updated record
        """
        if table_name == "Ideas":
            table = self.ideas_table
        elif table_name == "Idea Concepts":
            table = self.idea_concepts_table
        elif table_name == "Script":
            table = self.script_table
        elif table_name == "Images":
            table = self.images_table
        else:
            raise ValueError(f"Unknown table: {table_name}")
        
        return table.update(record_id, fields)
