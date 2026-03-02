"""Airtable API client for Idea Concepts, Ideas (legacy), Script, and Images tables."""

import os
from pyairtable import Api, Table
from typing import Optional, Any


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
        - Image Style Override    : Long Text — custom instructions for image prompt prefix
        - Thumbnail Style Override: Long Text — custom instructions for thumbnail template

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
        return self.get_ideas_by_status("Ready For Scripting", limit)

    def get_ideas_ready_for_visuals(self, limit: int = 1) -> list[dict]:
        """Get ideas with status 'Ready For Visuals'."""
        return self.get_ideas_by_status("Ready For Visuals", limit)

    def get_all_ideas(self) -> list[dict]:
        """Get all ideas from the Idea Concepts table."""
        records = self.idea_concepts_table.all(sort=["Status"])
        return [{"id": r["id"], **r["fields"]} for r in records]

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
            "Status": "Idea Logged",
            "Video Title": idea_data.get("viral_title", idea_data.get("Video Title", "")),
            "Hook Script": idea_data.get("hook_script", idea_data.get("Hook Script", "")),
            "Past Context": idea_data.get("narrative_logic", {}).get("past_context", idea_data.get("Past Context", "")),
            "Present Parallel": idea_data.get("narrative_logic", {}).get("present_parallel", idea_data.get("Present Parallel", "")),
            "Future Prediction": idea_data.get("narrative_logic", {}).get("future_prediction", idea_data.get("Future Prediction", "")),
            "Thumbnail Prompt": idea_data.get("thumbnail_visual", idea_data.get("Thumbnail Prompt", "")),
            "Writer Guidance": idea_data.get("writer_guidance", idea_data.get("Writer Guidance", "")),
            "Original DNA": idea_data.get("original_dna", idea_data.get("Original DNA", "")),
            "Source": source,
        }

        # Optional fields (may not exist in Airtable yet)
        optional_fields = {}
        if idea_data.get("reference_url") or idea_data.get("Reference URL"):
            optional_fields["Reference URL"] = idea_data.get("reference_url", idea_data.get("Reference URL", ""))
        if idea_data.get("modeled_from"):
            optional_fields["Idea Reasoning"] = idea_data.get("modeled_from")
        if idea_data.get("source_views"):
            optional_fields["Source Views"] = idea_data.get("source_views")
        if idea_data.get("source_channel"):
            optional_fields["Source Channel"] = idea_data.get("source_channel")

        # Rich schema fields (added by setup_airtable_fields.py)
        rich_field_keys = [
            "Framework Angle", "Headline", "Timeliness Score",
            "Audience Fit Score", "Content Gap Score", "Monetization Risk",
            "Source URLs", "Executive Hook", "Thesis", "Date Surfaced",
            "Research Payload", "Thematic Framework",
        ]
        for key in rich_field_keys:
            if key in idea_data and idea_data[key]:
                optional_fields[key] = idea_data[key]

        # Also accept pipeline_writer fields passed directly in idea_data
        pipeline_keys = [
            "Script", "Scene File Path", "Accent Color",
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
                "Status": core_fields.get("Status", "Idea Logged"),
                "Video Title": core_fields.get("Video Title", ""),
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
            record_title = r["fields"].get("Video Title", "")
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
        try:
            record = self.idea_concepts_table.update(record_id, fields, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            error_msg = str(e)
            if "UNKNOWN_FIELD_NAME" not in error_msg and "Unknown field name" not in error_msg:
                raise

            # Retry by dropping unknown fields one at a time
            remaining = dict(fields)
            max_retries = len(fields)
            for _ in range(max_retries):
                bad_field = self._extract_bad_field(error_msg)
                if bad_field and bad_field in remaining:
                    print(f"    ⚠️ Field '{bad_field}' not in Airtable, dropping it")
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
        voice_id: str = "G17SuINrv2H9FC6nvetn",
        sources: str = "",
    ) -> dict:
        """Create a new script record for a scene."""
        fields = {
            "scene": scene_number,
            "Scene text": scene_text,
            "Title": title,
            "Voice ID": voice_id,
            "Script Status": "Create",  # Single select, not array
        }
        # Store full source list on scene 1 for YouTube show notes
        if sources and scene_number == 1:
            fields["Sources"] = sources
        try:
            record = self.script_table.create(fields, typecast=True)
        except Exception as e:
            # Gracefully drop Sources field if not yet in Airtable
            if "UNKNOWN_FIELD_NAME" in str(e) and "Sources" in fields:
                print("    ⚠️ Sources field not on Script table — run setup_airtable_fields.py")
                del fields["Sources"]
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
            "Script Status": "Finished",
            "Voice Status": "Done",
        }
        if voice_over_url:
            updates["Voice Over"] = [{"url": voice_over_url}]
        return self.update_script_record(record_id, updates)
    
    # ==================== IMAGES TABLE ====================
    
    def get_pending_images(self) -> list[dict]:
        """Get image records with status 'Pending', ordered by scene and index."""
        records = self.images_table.all(
            formula='{Status} = "Pending"',
            sort=["Scene", "Image Index"],
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
            "Scene": scene_number,
            "Image Index": concept_index,
            "Sentence Text": sentence_text,
            "Image Prompt": image_prompt,
            "Shot Type": composition,
            "Video Title": video_title,
            "Aspect Ratio": aspect_ratio,
            "Status": "Pending",
            "Sentence Index": concept_index,
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
            "Image": [{"url": image_url}],
            "Status": "Done",
        }
        # Note: Drive Image URL field removed - not in Airtable schema
        record = self.images_table.update(record_id, updates, typecast=True)
        return {"id": record["id"], **record["fields"]}

    def update_image_video_url(
        self,
        record_id: str,
        video_url: str,
    ) -> dict:
        """Update an image record with the generated video URL."""
        # Note: 'Video' field based on screenshot, 'Video Status' to Done
        updates = {
            "Video": [{"url": video_url}], # Attachment field uses list of dicts
            "Video Status": "Done",
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
            "Video Prompt": prompt,
            "Video Status": "Pending",
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
            updates["Shot Type"] = shot_type
        if is_hero_shot is not None:
            updates["Hero Shot"] = is_hero_shot
        if video_clip_url is not None:
            updates["Video Clip URL"] = video_clip_url
        if animation_status is not None:
            updates["Animation Status"] = animation_status
        if video_duration is not None:
            updates["Video Duration"] = video_duration

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
                core_fields = ["Video Clip URL"]
                core_updates = {k: v for k, v in updates.items() if k in core_fields}
                if core_updates:
                    try:
                        record = self.images_table.update(record_id, core_updates, typecast=True)
                        return {"id": record["id"], **record["fields"]}
                    except Exception:
                        pass
                return {"id": record_id, "warning": "Animation fields not found in Airtable"}
            raise

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
                match({"Video Title": video_title}),
                match({"Status": "Done"}),
            ),
            sort=["Scene", "Image Index"],
        )
        # Filter python side for empty video
        # 'Video' is an attachment field, so check if it's empty or None
        return [{"id": r["id"], **r["fields"]} for r in records if not r["fields"].get("Video")]
    
    def get_pending_images_for_video(self, video_title: str) -> list[dict]:
        """Get pending image records for a specific video, ordered by scene and index."""
        from pyairtable.formulas import match, AND
        records = self.images_table.all(
            formula=AND(
                match({"Video Title": video_title}),
                match({"Status": "Pending"}),
            ),
            sort=["Scene", "Image Index"],
        )
        return [{"id": r["id"], **r["fields"]} for r in records]
    
    def get_all_images_for_video(self, video_title: str) -> list[dict]:
        """Get all image records for a specific video."""
        from pyairtable.formulas import match
        records = self.images_table.all(
            formula=match({"Video Title": video_title}),
            sort=["Scene", "Image Index"],
        )
        return [{"id": r["id"], **r["fields"]} for r in records]

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
