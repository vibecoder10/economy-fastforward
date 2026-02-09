"""Airtable client for the animation pipeline's Project and Scenes tables.

Connects to the R50 | Cinematic Adverts System base (appB9RWwCgywdwYrT),
separate from the main pipeline's Airtable base.
"""

import os
from pyairtable import Api, Table
from typing import Optional, Any

from animation.config import (
    AIRTABLE_API_KEY,
    AIRTABLE_ANIMATION_BASE_ID,
    AIRTABLE_PROJECT_TABLE_ID,
    AIRTABLE_SCENES_TABLE_ID,
)


class AnimationAirtableClient:
    """Client for the animation pipeline's Airtable tables."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_id: Optional[str] = None,
    ):
        self.api_key = api_key or AIRTABLE_API_KEY
        if not self.api_key:
            raise ValueError("AIRTABLE_API_KEY not found in environment")

        self.base_id = base_id or AIRTABLE_ANIMATION_BASE_ID
        self.api = Api(self.api_key)

        # Lazy-load table references
        self._project_table = None
        self._scenes_table = None

    @property
    def project_table(self) -> Table:
        """Get the Project table."""
        if self._project_table is None:
            self._project_table = self.api.table(self.base_id, AIRTABLE_PROJECT_TABLE_ID)
        return self._project_table

    @property
    def scenes_table(self) -> Table:
        """Get the Scenes table."""
        if self._scenes_table is None:
            self._scenes_table = self.api.table(self.base_id, AIRTABLE_SCENES_TABLE_ID)
        return self._scenes_table

    # ==================== PROJECT TABLE ====================

    def get_projects_by_status(self, status: str, limit: int = 1) -> list[dict]:
        """Get projects with the specified status."""
        records = self.project_table.all(
            formula=f'{{Status}} = "{status}"',
            max_records=limit,
        )
        return [{"id": r["id"], **r["fields"]} for r in records]

    def get_project_by_id(self, record_id: str) -> Optional[dict]:
        """Get a single project by record ID."""
        try:
            record = self.project_table.get(record_id)
            return {"id": record["id"], **record["fields"]}
        except Exception:
            return None

    def update_project_status(self, record_id: str, status: str) -> dict:
        """Update the status of a project."""
        record = self.project_table.update(record_id, {"Status": status}, typecast=True)
        return {"id": record["id"], **record["fields"]}

    def update_project_fields(self, record_id: str, fields: dict) -> dict:
        """Update multiple fields on a project record."""
        try:
            record = self.project_table.update(record_id, fields, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            if "UNKNOWN_FIELD_NAME" in str(e):
                print(f"    \u26a0\ufe0f Some project fields missing in Airtable: {str(e)[:100]}")
                return {"id": record_id, "warning": "Some fields not found"}
            raise

    # ==================== SCENES TABLE ====================

    def get_scenes_for_project(self, project_name: str) -> list[dict]:
        """Get all scenes for a project, ordered by scene_order."""
        from pyairtable.formulas import match
        records = self.scenes_table.all(
            formula=match({"Project Name": project_name}),
            sort=["scene_order"],
        )
        return [{"id": r["id"], **r["fields"]} for r in records]

    def get_scenes_needing_images(self, project_name: str) -> list[dict]:
        """Get scenes where prompt done = true but image done = false."""
        from pyairtable.formulas import match, AND, FIELD
        records = self.scenes_table.all(
            formula=AND(
                match({"Project Name": project_name}),
                match({"prompt done": True}),
            ),
            sort=["scene_order"],
        )
        # Filter in Python for image done = false (unchecked checkboxes may be missing)
        return [
            {"id": r["id"], **r["fields"]}
            for r in records
            if not r["fields"].get("image done")
        ]

    def get_scenes_needing_animation(self, project_name: str) -> list[dict]:
        """Get animated scenes where image done = true but video done = false."""
        from pyairtable.formulas import match, AND
        records = self.scenes_table.all(
            formula=AND(
                match({"Project Name": project_name}),
                match({"image done": True}),
                match({"scene_type": "animated"}),
            ),
            sort=["scene_order"],
        )
        return [
            {"id": r["id"], **r["fields"]}
            for r in records
            if not r["fields"].get("video done")
        ]

    def get_scenes_needing_qc(self, project_name: str) -> list[dict]:
        """Get scenes with video done = true but no qc_score."""
        from pyairtable.formulas import match, AND
        records = self.scenes_table.all(
            formula=AND(
                match({"Project Name": project_name}),
                match({"video done": True}),
            ),
            sort=["scene_order"],
        )
        return [
            {"id": r["id"], **r["fields"]}
            for r in records
            if r["fields"].get("qc_score") is None
        ]

    def get_completed_scenes_count(self, project_name: str) -> int:
        """Count scenes where video done = true for a project."""
        from pyairtable.formulas import match, AND
        records = self.scenes_table.all(
            formula=AND(
                match({"Project Name": project_name}),
                match({"video done": True}),
            ),
        )
        return len(records)

    def create_scene(self, fields: dict) -> dict:
        """Create a new scene record.

        Args:
            fields: Dict of field names to values. Should include:
                - Project Name, scene, scene_order, scene_type, etc.

        Returns:
            Created record dict
        """
        try:
            record = self.scenes_table.create(fields, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            if "UNKNOWN_FIELD_NAME" in str(e):
                print(f"    \u26a0\ufe0f Some scene fields missing in Airtable, saving core fields only")
                # Fallback: save only the fields that exist in the original schema
                core_fields = {
                    k: v for k, v in fields.items()
                    if k in [
                        "execution_id", "Project Name", "scene", "start_image_prompt",
                        "end_image_prompt", "transition_prompt", "prompt done",
                    ]
                }
                record = self.scenes_table.create(core_fields, typecast=True)
                return {"id": record["id"], **record["fields"]}
            raise

    def update_scene(self, record_id: str, fields: dict) -> dict:
        """Update a scene record."""
        try:
            record = self.scenes_table.update(record_id, fields, typecast=True)
            return {"id": record["id"], **record["fields"]}
        except Exception as e:
            if "UNKNOWN_FIELD_NAME" in str(e):
                print(f"    \u26a0\ufe0f Some scene fields missing in Airtable: {str(e)[:100]}")
                return {"id": record_id, "warning": "Some fields not found"}
            raise

    def update_scene_images(
        self,
        record_id: str,
        start_image_url: str,
        end_image_url: str,
    ) -> dict:
        """Upload start and end frame images to a scene."""
        updates = {
            "start_image": [{"url": start_image_url}],
            "end_image": [{"url": end_image_url}],
            "image done": True,
        }
        return self.update_scene(record_id, updates)

    def update_scene_video(self, record_id: str, video_url: str) -> dict:
        """Upload the animated video clip to a scene."""
        updates = {
            "scene_video": [{"url": video_url}],
            "video done": True,
        }
        return self.update_scene(record_id, updates)

    def update_scene_qc(
        self,
        record_id: str,
        qc_score: int,
        qc_notes: str,
    ) -> dict:
        """Write QC results to a scene."""
        updates = {
            "qc_score": qc_score,
            "qc_notes": qc_notes,
        }
        return self.update_scene(record_id, updates)

    def increment_regen_count(self, record_id: str, current_count: int) -> dict:
        """Increment the regen count for a scene."""
        return self.update_scene(record_id, {"regen_count": current_count + 1})

    def reset_scene_for_regen(self, record_id: str) -> dict:
        """Reset a scene's video fields for regeneration."""
        updates = {
            "video done": False,
            "scene_video": [],
            "qc_score": None,
            "qc_notes": None,
        }
        return self.update_scene(record_id, updates)
