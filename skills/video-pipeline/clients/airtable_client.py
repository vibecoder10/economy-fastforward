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
    
    def get_ideas_ready_for_visuals(self, limit: int = 1) -> list[dict]:
        """Get ideas with status 'Ready For Visuals'."""
        return self.get_ideas_by_status("Ready For Visuals", limit)
    
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
        
    def update_idea_field(self, record_id: str, field_name: str, value) -> dict:
        """Update a single field on an idea record."""
        record = self.ideas_table.update(record_id, {field_name: value})
        return {"id": record["id"], **record["fields"]}

    def update_idea_thumbnail(self, record_id: str, thumbnail_url: str) -> dict:
        """Update the thumbnail attachment of an idea."""
        record = self.ideas_table.update(record_id, {"Thumbnail": [{"url": thumbnail_url}]})
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
        image_prompt: str,
        video_title: str,
        sentence_text: str = "",
        duration_seconds: float = 0.0,
        cumulative_start: float = 0.0,
        aspect_ratio: str = "16:9",
        **kwargs,
    ) -> dict:
        """Create a sentence-aligned image prompt record."""
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
        }
        record = self.images_table.create(fields)
        return {"id": record["id"], **record["fields"]}

    def create_segment_image_record(
        self,
        scene_number: int,
        segment_index: int,
        image_prompt: str,
        video_title: str,
        segment_text: str = "",
        duration_seconds: float = 0.0,
        cumulative_start: float = 0.0,
        visual_concept: str = "",
        aspect_ratio: str = "16:9",
        **kwargs,
    ) -> dict:
        """Create a semantic segment image record."""
        fields = {
            "Scene": scene_number,
            "Image Index": segment_index,
            "Image Prompt": image_prompt,
            "Video Title": video_title,
            "Aspect Ratio": aspect_ratio,
            "Status": "Pending",
            "Sentence Text": segment_text,
            "Duration (s)": duration_seconds,
            "Sentence Index": segment_index,
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
