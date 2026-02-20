"""Animation Pipeline Orchestrator.

Phases:
1. Scene Planning (Sonnet) - Break script into scenes with glow arc
2. Image Prompt Generation (Sonnet) - Create detailed prompts
3. Image Generation (Seed Dream 4.5 Edit) - Generate scene images with Core Image reference
4. [MANUAL] Video Generation (Veo 3.1) - Requires --animate flag
"""

import os
import asyncio
import json
from typing import Optional
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '.env'))

from animation.scene_planner import ScenePlanner
from animation.image_generator import ImagePromptGenerator
from animation.airtable_client import AnimationAirtableClient

# Import image client from parent
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clients.image_client import ImageClient
from clients.google_client import GoogleClient


class AnimationPipeline:
    """Orchestrates the full animation pipeline."""

    # Cost tracking
    COST_PER_IMAGE = 0.0325  # Seed Dream 4.5 Edit (6.5 credits)
    COST_PER_VIDEO = 0.10    # Veo 3.1

    def __init__(self):
        self.airtable = AnimationAirtableClient()
        self.scene_planner = ScenePlanner()
        self.image_generator = ImagePromptGenerator()
        self.image_client = ImageClient()
        self.google_client = GoogleClient()

        # Pipeline state
        self.project = None
        self.scenes = []
        self.total_cost = 0.0
        self.core_image_url = ""

    async def load_project(self, status: str = "Create") -> Optional[dict]:
        """Load project with given status."""
        self.project = await self.airtable.get_project_by_status(status)
        if self.project:
            print(f"📁 Loaded project: {self.project.get('Project Name')}")
            # Extract Core Image URL from the project record
            core_image_attachments = self.project.get("Core Image", [])
            if core_image_attachments and isinstance(core_image_attachments, list):
                self.core_image_url = core_image_attachments[0].get("url", "")
            if self.core_image_url:
                print(f"🖼️  Core Image: {self.core_image_url[:80]}...")
            else:
                print(f"⚠️  No Core Image found on project — image generation will fail")
        return self.project

    async def run_scene_planning(self) -> list:
        """Phase 1: Plan scenes from script."""
        if not self.project:
            raise ValueError("No project loaded")

        print("\n" + "=" * 60)
        print("PHASE 1: SCENE PLANNING")
        print("=" * 60)

        script = self.project.get("script", "")
        creative_direction = self.project.get("Creative Direction", "")

        if not script:
            raise ValueError("Project has no script")

        # Extract glow and color arcs from creative direction
        glow_curve = "70 → 45 → 15 → 100"  # Default
        color_arc = "warm → cool → cold → warm"  # Default

        # Plan scenes
        result = await self.scene_planner.plan_scenes(
            script=script,
            creative_direction=creative_direction,
            glow_curve=glow_curve,
            color_arc=color_arc,
        )

        if "error" in result:
            raise ValueError(f"Scene planning failed: {result['error']}")

        self.scenes = result.get("scenes", [])
        print(f"✅ Planned {len(self.scenes)} scenes")

        # Save to Airtable
        print("\nSaving scenes to Airtable...")
        created = await self.airtable.create_scenes(
            self.project.get("Project Name"),
            self.scenes,
        )
        print(f"✅ Created {len(created)} scene records")

        # Reload scenes from Airtable to get IDs
        self.scenes = await self.airtable.get_scenes_for_project(
            self.project.get("Project Name")
        )
        print(f"  Loaded {len(self.scenes)} scenes with IDs")

        # Update project with total scenes
        await self.airtable.update_project(
            self.project["id"],
            {
                "total_scenes": len(self.scenes),
                "scenes_complete": 0,
            },
        )

        return self.scenes

    async def run_image_prompts(self) -> list:
        """Phase 2: Generate image prompts for all scenes."""
        print("\n" + "=" * 60)
        print("PHASE 2: IMAGE PROMPT GENERATION")
        print("=" * 60)

        if not self.scenes:
            # Load from Airtable
            self.scenes = await self.airtable.get_scenes_for_project(
                self.project.get("Project Name")
            )

        if not self.scenes:
            raise ValueError("No scenes to generate prompts for")

        creative_direction = self.project.get("Creative Direction", "")

        # Generate prompts
        self.scenes = await self.image_generator.generate_prompts_for_scenes(
            self.scenes,
            creative_direction,
        )

        # Update Airtable with prompts
        print("\nSaving prompts to Airtable...")
        for scene in self.scenes:
            if scene.get("start_image_prompt") and scene.get("id"):
                await self.airtable.update_scene(
                    scene["id"],
                    {"start_image_prompt": scene["start_image_prompt"]},
                )

        print(f"✅ Generated {len(self.scenes)} image prompts")
        return self.scenes

    async def run_image_generation(self) -> dict:
        """Phase 3: Generate images for all scenes."""
        print("\n" + "=" * 60)
        print("PHASE 3: IMAGE GENERATION (Seed Dream 4.5 Edit)")
        print("=" * 60)

        if not self.scenes:
            self.scenes = await self.airtable.get_scenes_for_project(
                self.project.get("Project Name")
            )

        # Filter to scenes needing images
        pending = [s for s in self.scenes if not s.get("start_image")]
        print(f"Scenes needing images: {len(pending)}")

        if not pending:
            print("✅ All scenes have images")
            return {"images_generated": 0, "cost": 0}

        # Cost estimate
        estimated_cost = len(pending) * self.COST_PER_IMAGE
        print(f"Estimated cost: ${estimated_cost:.2f}")

        # Get or create project folder
        folder = self.google_client.get_or_create_folder(self.project.get("Project Name"))
        folder_id = folder["id"]

        images_generated = 0
        image_cost = 0.0

        for i, scene in enumerate(pending, 1):
            scene_num = scene.get("scene_order", i)
            prompt = scene.get("start_image_prompt")

            if not prompt:
                print(f"  Scene {scene_num}: No prompt, skipping")
                continue

            print(f"\n  [{i}/{len(pending)}] Scene {scene_num}: Generating image...")
            print(f"    Type: {scene.get('scene_type')}")
            print(f"    Glow: {scene.get('glow_state')} ({scene.get('glow_behavior')})")

            # Generate image using Seed Dream 4.5 Edit with Core Image reference
            if not self.core_image_url:
                print(f"    ❌ No Core Image — skipping")
                continue
            result = await self.image_client.generate_scene_image(prompt, self.core_image_url)

            if result and result.get("url"):
                image_url = result["url"]
                seed = result.get("seed")

                # Download and upload to Drive
                print("    Downloading...")
                image_content = await self.image_client.download_image(image_url)

                filename = f"Scene_{str(scene_num).zfill(2)}.png"
                print(f"    Uploading to Drive: {filename}")

                drive_file = self.google_client.upload_image(image_content, filename, folder_id)
                drive_url = self.google_client.make_file_public(drive_file["id"])

                # Update Airtable
                await self.airtable.update_scene(
                    scene["id"],
                    {
                        "start_image": [{"url": drive_url}],
                        "image done": True,
                    },
                )

                images_generated += 1
                image_cost += self.COST_PER_IMAGE
                print(f"    ✅ Done! (${image_cost:.2f} total)")

            else:
                print(f"    ❌ Image generation failed")

        # Update project
        await self.airtable.update_project(
            self.project["id"],
            {
                "scenes_complete": images_generated,
                "animation_spend": image_cost,
            },
        )

        self.total_cost += image_cost

        print(f"\n✅ Generated {images_generated} images")
        print(f"   Total cost: ${image_cost:.2f}")

        return {"images_generated": images_generated, "cost": image_cost}

    async def run_full_pipeline(self, skip_videos: bool = True) -> dict:
        """Run the full pipeline (images only by default).

        Args:
            skip_videos: If True, stop after image generation (default)
        """
        print("\n" + "=" * 60)
        print("🎬 ANIMATION PIPELINE")
        print("=" * 60)

        # Load project
        project = await self.load_project("Create")
        if not project:
            return {"error": "No project with 'Create' status found"}

        # Check for existing scenes
        existing_scenes = await self.airtable.get_scenes_for_project(
            project.get("Project Name")
        )

        if existing_scenes:
            print(f"Found {len(existing_scenes)} existing scenes")
            self.scenes = existing_scenes
        else:
            # Phase 1: Scene Planning
            await self.run_scene_planning()

        # Check for prompts
        scenes_with_prompts = [s for s in self.scenes if s.get("start_image_prompt")]
        if len(scenes_with_prompts) < len(self.scenes):
            # Phase 2: Image Prompts
            await self.run_image_prompts()

        # Phase 3: Image Generation
        image_result = await self.run_image_generation()

        if skip_videos:
            print("\n" + "=" * 60)
            print("⏸️  STOPPED BEFORE VIDEO GENERATION")
            print("    To generate videos, run with --animate flag")
            print("=" * 60)
        else:
            # Phase 4: Video Generation (not implemented yet)
            print("\n⚠️ Video generation not yet implemented")

        # Final summary
        print("\n" + "=" * 60)
        print("📊 PIPELINE SUMMARY")
        print("=" * 60)
        print(f"  Project: {project.get('Project Name')}")
        print(f"  Scenes: {len(self.scenes)}")
        print(f"  Images generated: {image_result.get('images_generated', 0)}")
        print(f"  Total cost: ${self.total_cost:.2f}")

        return {
            "project": project.get("Project Name"),
            "scenes": len(self.scenes),
            "images_generated": image_result.get("images_generated", 0),
            "total_cost": self.total_cost,
        }


async def main():
    """Run the animation pipeline."""
    pipeline = AnimationPipeline()
    result = await pipeline.run_full_pipeline(skip_videos=True)
    print(f"\n✅ Pipeline complete: {result}")


if __name__ == "__main__":
    asyncio.run(main())
