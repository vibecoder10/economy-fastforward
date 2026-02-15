"""Airtable API client for Idea Concepts, Ideas (legacy), Script, and Images tables."""

import os
from pyairtable import Api, Table
from typing import Optional, Any


class AirtableClient:
    """Client for Airtable API operations."""

    # Table IDs from the n8n workflow
    DEFAULT_BASE_ID = "appCIcC58YSTwK3CE"
    IDEAS_TABLE_ID = "tblrAsJglokZSkC8m"          # Legacy — preserved as archive
    SCRIPT_TABLE_ID = "tbluGSepeZNgb0NxG"
    IMAGES_TABLE_ID = "tbl3luJ0zsWu0MYYz"

    # Idea Concepts — single source of truth for ALL new ideas
    # Set AIRTABLE_IDEA_CONCEPTS_TABLE_ID in .env once the table is created
    IDEA_CONCEPTS_TABLE_ID = None  # populated from env in __init__

    def __init__(self, api_key: Optional[str] = None, base_id: Optional[str] = None):
        self.api_key = api_key or os.getenv("AIRTABLE_API_KEY")
        if not self.api_key:
            raise ValueError("AIRTABLE_API_KEY not found in environment")

        self.base_id = base_id or os.getenv("AIRTABLE_BASE_ID", self.DEFAULT_BASE_ID)
        self.api = Api(self.api_key)

        # Idea Concepts table ID from env (falls back to Ideas table if not set)
        self.IDEA_CONCEPTS_TABLE_ID = os.getenv(
            "AIRTABLE_IDEA_CONCEPTS_TABLE_ID",
            self.IDEAS_TABLE_ID,  # Fallback to legacy Ideas table
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
                    "url_analysis", "trending", "format_library", "research_agent"
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
            if "UNKNOWN_FIELD_NAME" in error_msg:
                # Identify the bad field from the error message and retry without it
                import re
                bad_match = re.search(r'"([^"]+)"', error_msg.split("UNKNOWN_FIELD_NAME")[-1])
                bad_field = bad_match.group(1) if bad_match else None

                # Retry by dropping unknown fields one at a time
                remaining = dict(all_fields)
                for _attempt in range(len(optional_fields) + 1):
                    if bad_field and bad_field in remaining:
                        print(f"    ⚠️ Field '{bad_field}' not in Airtable, dropping it")
                        del remaining[bad_field]
                    else:
                        # Drop all optional fields as last resort
                        remaining = dict(core_fields)

                    try:
                        record = self.idea_concepts_table.create(remaining, typecast=True)
                        if remaining != all_fields:
                            dropped = set(all_fields) - set(remaining)
                            print(f"    ⚠️ Saved without fields: {dropped}")
                        return {"id": record["id"], **record["fields"]}
                    except Exception as retry_err:
                        error_msg = str(retry_err)
                        if "UNKNOWN_FIELD_NAME" not in error_msg:
                            raise
                        bad_match = re.search(
                            r'"([^"]+)"',
                            error_msg.split("UNKNOWN_FIELD_NAME")[-1],
                        )
                        bad_field = bad_match.group(1) if bad_match else None

                # Final fallback: core fields only
                print(f"    ⚠️ Multiple fields missing, saving core fields only")
                record = self.idea_concepts_table.create(core_fields, typecast=True)
                return {"id": record["id"], **record["fields"]}
            raise

    def update_idea_status(self, record_id: str, status: str) -> dict:
        """Update the status of an idea in the Idea Concepts table."""
        record = self.idea_concepts_table.update(record_id, {"Status": status}, typecast=True)
        return {"id": record["id"], **record["fields"]}

    def update_idea_field(self, record_id: str, field_name: str, value) -> dict:
        """Update a single field on an idea record."""
        record = self.idea_concepts_table.update(record_id, {field_name: value})
        return {"id": record["id"], **record["fields"]}

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
        """Get all script records for a specific video title, ordered by scene number."""
        # Use pyairtable's match function which handles escaping properly
        from pyairtable.formulas import match
        records = self.script_table.all(
            formula=match({"Title": title}),
            sort=["scene"],
        )
        return [{"id": r["id"], **r["fields"]} for r in records]
    
    def create_script_record(
        self,
        scene_number: int,
        scene_text: str,
        title: str,
        voice_id: str = "G17SuINrv2H9FC6nvetn",
    ) -> dict:
        """Create a new script record for a scene."""
        fields = {
            "scene": scene_number,
            "Scene text": scene_text,
            "Title": title,
            "Voice ID": voice_id,
            "Script Status": "Create",  # Single select, not array
        }
        record = self.script_table.create(fields)
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
    
    def create_image_prompt_record(
        self,
        scene_number: int,
        image_index: int,
        image_prompt: str,
        video_title: str,
        aspect_ratio: str = "16:9",
    ) -> dict:
        """Create a new image prompt record."""
        fields = {
            "Scene": scene_number,
            "Image Index": image_index,
            "Image Prompt": image_prompt,
            "Video Title": video_title,
            "Aspect Ratio": aspect_ratio,
            "Status": "Pending",
        }
        record = self.images_table.create(fields)
        return {"id": record["id"], **record["fields"]}
    
    def create_sentence_image_record(
        self,
        scene_number: int,
        sentence_index: int,
        sentence_text: str,
        duration_seconds: float,
        image_prompt: str,
        video_title: str,
        cumulative_start: float = 0.0,
        aspect_ratio: str = "16:9",
        shot_type: str = None,
    ) -> dict:
        """Create a sentence-aligned image prompt record.

        DEPRECATED: Use create_segment_image_record for semantic segmentation.
        """
        fields = {
            "Scene": scene_number,
            "Image Index": sentence_index,
            "Image Prompt": image_prompt,
            "Video Title": video_title,
            "Aspect Ratio": aspect_ratio,
            "Status": "Pending",
            "Sentence Text": sentence_text,
            "Duration (s)": float(duration_seconds),
            "Sentence Index": sentence_index,
            # Note: "Start Time (s)" field removed - Airtable field type issue
        }
        if shot_type:
            fields["Shot Type"] = shot_type
        record = self.images_table.create(fields, typecast=True)
        return {"id": record["id"], **record["fields"]}

    def create_segment_image_record(
        self,
        scene_number: int,
        segment_index: int,
        segment_text: str,
        duration_seconds: float,
        image_prompt: str,
        video_title: str,
        visual_concept: str = "",
        cumulative_start: float = 0.0,
        aspect_ratio: str = "16:9",
    ) -> dict:
        """Create a semantic segment image record.

        This is the smart segmentation format that groups sentences by visual concept
        and enforces max duration for AI video generation.

        Args:
            scene_number: The scene number
            segment_index: Position within scene (1-based)
            segment_text: The narration text for this segment (may be multiple sentences)
            duration_seconds: How long this segment runs (max 10s for AI video)
            image_prompt: The image generation prompt
            video_title: Title of the video
            visual_concept: Description of why this is a distinct visual segment
            cumulative_start: Start time within scene (seconds) for video stitching
            aspect_ratio: Image aspect ratio

        Returns:
            Created record dict
        """
        fields = {
            "Scene": scene_number,
            "Image Index": segment_index,
            "Image Prompt": image_prompt,
            "Video Title": video_title,
            "Aspect Ratio": aspect_ratio,
            "Status": "Pending",
            # Segment-level fields for semantic alignment
            "Sentence Text": segment_text,  # Reuse field, contains full segment text
            "Duration (s)": float(duration_seconds),
            "Sentence Index": segment_index,  # Reuse as segment index
            "Visual Concept": visual_concept,  # NEW: Why this is a distinct visual
            # Note: "Start Time (s)" field removed - Airtable field type issue
        }
        record = self.images_table.create(fields)
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
