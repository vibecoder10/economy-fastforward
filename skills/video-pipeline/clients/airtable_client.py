"""Airtable API client for Ideas, Script, and Images tables."""

import os
from pyairtable import Api, Table
from typing import Optional, Any


class AirtableClient:
    """Client for Airtable API operations."""
    
    # Table IDs from the n8n workflow
    DEFAULT_BASE_ID = "appCIcC58YSTwK3CE"
    IDEAS_TABLE_ID = "tblrAsJglokZSkC8m"
    SCRIPT_TABLE_ID = "tbluGSepeZNgb0NxG"
    IMAGES_TABLE_ID = "tbl3luJ0zsWu0MYYz"
    
    def __init__(self, api_key: Optional[str] = None, base_id: Optional[str] = None):
        self.api_key = api_key or os.getenv("AIRTABLE_API_KEY")
        if not self.api_key:
            raise ValueError("AIRTABLE_API_KEY not found in environment")
        
        self.base_id = base_id or os.getenv("AIRTABLE_BASE_ID", self.DEFAULT_BASE_ID)
        self.api = Api(self.api_key)
        
        # Initialize table references
        self._ideas_table = None
        self._script_table = None
        self._images_table = None
    
    @property
    def ideas_table(self) -> Table:
        """Get the Ideas table."""
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
    
    # ==================== IDEAS TABLE ====================
    
    def get_ideas_by_status(self, status: str, limit: int = 1) -> list[dict]:
        """Get ideas with the specified status."""
        records = self.ideas_table.all(
            formula=f'{{Status}} = "{status}"',
            max_records=limit,
        )
        return [{"id": r["id"], **r["fields"]} for r in records]
    
    def get_ideas_ready_for_scripting(self, limit: int = 1) -> list[dict]:
        """Get ideas with status 'Ready For Scripting'."""
        return self.get_ideas_by_status("Ready For Scripting", limit)
    
    def get_ideas_ready_for_image_prompts(self, limit: int = 1) -> list[dict]:
        """Get ideas with status 'Ready For Image Prompts'."""
        return self.get_ideas_by_status("Ready For Image Prompts", limit)

    def get_ideas_ready_for_images(self, limit: int = 1) -> list[dict]:
        """Get ideas with status 'Ready for Images'."""
        return self.get_ideas_by_status("Ready for Images", limit)
    
    def get_all_ideas(self) -> list[dict]:
        """Get all ideas from the table."""
        records = self.ideas_table.all(sort=["Status"])
        return [{"id": r["id"], **r["fields"]} for r in records]
    
    def create_idea(self, idea_data: dict) -> dict:
        """Create a new idea record."""
        fields = {
            "Status": "Idea Logged",
            "Video Title": idea_data.get("viral_title", ""),
            "Hook Script": idea_data.get("hook_script", ""),
            "Past Context": idea_data.get("narrative_logic", {}).get("past_context", ""),
            "Present Parallel": idea_data.get("narrative_logic", {}).get("present_parallel", ""),
            "Future Prediction": idea_data.get("narrative_logic", {}).get("future_prediction", ""),
            "Thumbnail Prompt": idea_data.get("thumbnail_visual", ""),
            "Writer Guidance": idea_data.get("writer_guidance", ""),
            "Original DNA": idea_data.get("original_dna", ""),
        }
        record = self.ideas_table.create(fields)
        return {"id": record["id"], **record["fields"]}
    
    def update_idea_status(self, record_id: str, status: str) -> dict:
        """Update the status of an idea."""
        # Use typecast=True to handle new options if possible/permissive
        record = self.ideas_table.update(record_id, {"Status": status}, typecast=True)
        return {"id": record["id"], **record["fields"]}
        
    def update_idea_thumbnail(self, record_id: str, thumbnail_url: str) -> dict:
        """Update the thumbnail URL of an idea."""
        record = self.ideas_table.update(record_id, {"Thumbnail URL": thumbnail_url})
        return {"id": record["id"], **record["fields"]}
    
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
        voice_duration: Optional[float] = None,
    ) -> dict:
        """Mark a script record as finished.

        Args:
            record_id: Airtable record ID
            voice_over_url: URL to the generated voice audio
            voice_duration: Duration of the voice audio in seconds
        """
        updates = {
            "Script Status": "Finished",
            "Voice Status": "Done",
        }
        if voice_over_url:
            updates["Voice Over"] = [{"url": voice_over_url}]
        if voice_duration is not None:
            updates["Voice Duration (s)"] = voice_duration
        # typecast=True to auto-create Voice Duration field if needed
        record = self.script_table.update(record_id, updates, typecast=True)
        return {"id": record["id"], **record["fields"]}

    def get_script_voice_duration(self, video_title: str, scene_number: int) -> Optional[float]:
        """Get the voice duration for a specific scene.

        Args:
            video_title: Title of the video
            scene_number: Scene number

        Returns:
            Voice duration in seconds, or None if not available
        """
        from pyairtable.formulas import match, AND
        records = self.script_table.all(
            formula=AND(
                match({"Title": video_title}),
                match({"scene": scene_number}),
            ),
            max_records=1,
        )
        if records:
            return records[0]["fields"].get("Voice Duration (s)")
        return None

    def get_all_voice_durations(self, video_title: str) -> dict[int, float]:
        """Get all voice durations for a video.

        Args:
            video_title: Title of the video

        Returns:
            Dict mapping scene number to duration in seconds
        """
        scripts = self.get_scripts_by_title(video_title)
        durations = {}
        for script in scripts:
            scene = script.get("scene", 0)
            duration = script.get("Voice Duration (s)")
            if duration is not None:
                durations[scene] = duration
        return durations
    
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
            "Duration (s)": duration_seconds,
            "Sentence Index": sentence_index,
            "Start Time (s)": cumulative_start,
        }
        # typecast=True auto-creates fields if they don't exist
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
            "Duration (s)": duration_seconds,
            "Sentence Index": segment_index,  # Reuse as segment index
            "Start Time (s)": cumulative_start,
            "Visual Concept": visual_concept,  # NEW: Why this is a distinct visual
        }
        # typecast=True auto-creates fields if they don't exist
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
        if drive_url:
            updates["Drive Image URL"] = drive_url
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

    def delete_all_images_for_video(self, video_title: str) -> int:
        """Delete ALL image records for a specific video.

        Uses pyairtable's batch_delete for efficiency (deletes 10 at a time).

        Returns:
            Number of records deleted
        """
        from pyairtable.formulas import match
        records = self.images_table.all(
            formula=match({"Video Title": video_title}),
        )
        record_ids = [r["id"] for r in records]

        if not record_ids:
            print(f"    No image records found for '{video_title}'")
            return 0

        # pyairtable batch_delete handles chunking (max 10 per API call)
        self.images_table.batch_delete(record_ids)
        print(f"    Deleted {len(record_ids)} image records for '{video_title}'")
        return len(record_ids)
