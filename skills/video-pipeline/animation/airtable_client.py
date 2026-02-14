"""Airtable client for Animation Pipeline.

Connects to the separate animation base (appB9RWwCgywdwYrT).
"""

import os
import httpx
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()


class AnimationAirtableClient:
    """Client for Animation Pipeline Airtable base."""

    BASE_ID = "appB9RWwCgywdwYrT"
    PROJECT_TABLE_ID = "tblYiND5DkrZhIlLq"
    SCENES_TABLE_ID = "tblipThhapetdSJdm"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("AIRTABLE_API_KEY")
        if not self.api_key:
            raise ValueError("AIRTABLE_API_KEY not found")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def get_project_by_status(self, status: str) -> Optional[dict]:
        """Get a project by status."""
        url = f"https://api.airtable.com/v0/{self.BASE_ID}/{self.PROJECT_TABLE_ID}"
        params = {"filterByFormula": f"{{Status}}='{status}'", "maxRecords": 1}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, params=params, timeout=30.0)
            response.raise_for_status()
            records = response.json().get("records", [])

        if records:
            return {"id": records[0]["id"], **records[0].get("fields", {})}
        return None

    async def update_project(self, record_id: str, fields: dict) -> dict:
        """Update a project record."""
        url = f"https://api.airtable.com/v0/{self.BASE_ID}/{self.PROJECT_TABLE_ID}/{record_id}"

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers=self.headers,
                json={"fields": fields},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def create_scenes(self, project_name: str, scenes: List[dict]) -> List[dict]:
        """Create multiple scene records.

        Args:
            project_name: Name of the project (links scenes to project)
            scenes: List of scene dicts from scene planner

        Returns:
            List of created scene records
        """
        url = f"https://api.airtable.com/v0/{self.BASE_ID}/{self.SCENES_TABLE_ID}"

        # Airtable batch create limit is 10 records
        created = []

        for i in range(0, len(scenes), 10):
            batch = scenes[i:i + 10]
            records = []

            for scene in batch:
                fields = {
                    "Project Name": project_name,
                    "scene_order": scene.get("scene_order"),
                    "scene_type": scene.get("scene_type"),
                    "narrative_beat": scene.get("narrative_beat"),
                    "voiceover_text": scene.get("voiceover_text"),
                    "camera_direction": scene.get("camera_direction"),
                    "glow_state": scene.get("glow_state"),
                    "glow_behavior": scene.get("glow_behavior"),
                    "color_temperature": scene.get("color_temperature"),
                    "transition_out": scene.get("transition_out"),
                    "motion_description": scene.get("motion_description"),
                }

                # Add optional fields
                if scene.get("start_image_prompt"):
                    fields["start_image_prompt"] = scene["start_image_prompt"]
                if scene.get("end_image_prompt"):
                    fields["end_image_prompt"] = scene["end_image_prompt"]
                if scene.get("negative_prompt"):
                    fields["negative_prompt"] = scene["negative_prompt"]

                records.append({"fields": fields})

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=self.headers,
                    json={"records": records},
                    timeout=60.0,
                )
                response.raise_for_status()
                created.extend(response.json().get("records", []))

            print(f"  Created batch {i // 10 + 1}: {len(batch)} scenes")

        return created

    async def get_scenes_for_project(self, project_name: str) -> List[dict]:
        """Get all scenes for a project."""
        url = f"https://api.airtable.com/v0/{self.BASE_ID}/{self.SCENES_TABLE_ID}"
        params = {
            "filterByFormula": f"{{Project Name}}='{project_name}'",
            "sort[0][field]": "scene_order",
            "sort[0][direction]": "asc",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, params=params, timeout=30.0)
            response.raise_for_status()
            records = response.json().get("records", [])

        return [{"id": r["id"], **r.get("fields", {})} for r in records]

    async def get_scenes_for_project_by_id(self, scene_id: str) -> List[dict]:
        """Get a single scene by its Airtable record ID.

        Args:
            scene_id: The Airtable record ID (e.g., recXXXXXXXXXXXXXX)

        Returns:
            List with single scene dict, or empty list if not found
        """
        url = f"https://api.airtable.com/v0/{self.BASE_ID}/{self.SCENES_TABLE_ID}/{scene_id}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, timeout=30.0)
                response.raise_for_status()
                record = response.json()
                return [{"id": record["id"], **record.get("fields", {})}]
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return []
                raise

    async def update_scene(self, record_id: str, fields: dict) -> dict:
        """Update a scene record."""
        url = f"https://api.airtable.com/v0/{self.BASE_ID}/{self.SCENES_TABLE_ID}/{record_id}"

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers=self.headers,
                json={"fields": fields},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def update_scene_image(self, record_id: str, image_url: str, field: str = "start_image") -> dict:
        """Update a scene with an image attachment."""
        fields = {field: [{"url": image_url}]}
        return await self.update_scene(record_id, fields)

    async def update_scene_video(self, record_id: str, video_url: str) -> dict:
        """Update a scene with a video attachment."""
        fields = {"scene_video": [{"url": video_url}], "video done": True}
        return await self.update_scene(record_id, fields)


async def main():
    """Test the Airtable client."""
    client = AnimationAirtableClient()

    # Get the Create project
    project = await client.get_project_by_status("Create")
    if project:
        print(f"Found project: {project.get('Project Name')}")

        # Check existing scenes
        scenes = await client.get_scenes_for_project(project.get("Project Name"))
        print(f"Existing scenes: {len(scenes)}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
