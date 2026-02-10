"""Animation Pipeline Orchestrator

STATUS-DRIVEN WORKFLOW:
The pipeline reads from the R50 | Cinematic Adverts System Airtable base
and processes projects through these phases:

1. FIND:    Query Project table for Status = "Create"
2. PLAN:    Generate scene plan via Sonnet → write scenes to Airtable
3. FRAMES:  Generate start/end frame images for each scene
4. ANIMATE: Submit frame pairs to Veo 3.1 Fast for animated scenes
5. QC:      Run Haiku quality checks on completed clips
6. FINALIZE: Calculate costs, update status, notify via Slack

RULES:
- One project at a time
- Budget enforcement with kill switch
- Max 2 regeneration attempts per scene
- Sonnet for planning, Haiku for QC — never Opus
"""

import asyncio
import json
from typing import Optional

from animation.config import (
    ANIMATION_BUDGET_DEFAULT,
    MAX_REGEN_ATTEMPTS,
    PROJECT_STATUS_CREATE,
    PROJECT_STATUS_PLANNING,
    PROJECT_STATUS_GENERATING_FRAMES,
    PROJECT_STATUS_ANIMATING,
    PROJECT_STATUS_QC,
    PROJECT_STATUS_DONE,
    PROJECT_STATUS_FAILED,
    PROJECT_STATUS_BUDGET_EXCEEDED,
)
from animation.airtable import AnimationAirtableClient
from animation.scene_planner import ScenePlanner
from animation.image_generator import AnimationImageGenerator
from animation.animator import Animator
from animation.qc_checker import QCChecker
from animation.cost_tracker import CostTracker
from animation.notify import AnimationNotifier


class AnimationPipeline:
    """Orchestrates the full animation production pipeline."""

    def __init__(self):
        """Initialize all clients."""
        self.airtable = AnimationAirtableClient()
        self.planner = ScenePlanner()
        self.image_gen = AnimationImageGenerator()
        self.animator = Animator()
        self.qc = QCChecker()
        self.notifier = AnimationNotifier()

        # Pipeline state
        self.current_project: Optional[dict] = None
        self.project_name: Optional[str] = None
        self.cost_tracker: Optional[CostTracker] = None

    # Statuses that indicate a project we should process or resume
    RESUMABLE_STATUSES = [
        PROJECT_STATUS_CREATE,
        PROJECT_STATUS_PLANNING,
        PROJECT_STATUS_GENERATING_FRAMES,
        PROJECT_STATUS_ANIMATING,
        PROJECT_STATUS_QC,
        PROJECT_STATUS_FAILED,
    ]

    async def run(self) -> Optional[dict]:
        """Run the full animation pipeline for one project.

        Finds a project to process — either a new one (Status = "Create")
        or one that was interrupted mid-run — and resumes from wherever
        it left off. Each phase checks Airtable for remaining work, so
        re-running a phase that already completed is safe (it skips).

        Returns:
            Summary dict on completion, or None if no projects found
        """
        # Phase 1: Find a project (new or in-progress)
        project = self._find_project()
        if not project:
            print("  No projects found to process")
            return None

        self.current_project = project
        self.project_name = project.get("Project Name", project.get("id"))
        current_status = project.get("Status", "")
        budget = project.get("animation_budget", ANIMATION_BUDGET_DEFAULT)
        self.cost_tracker = CostTracker(budget=float(budget))

        print(f"\n{'='*60}")
        print(f"  🎬 Animation Pipeline: {self.project_name}")
        print(f"  📍 Current status: {current_status}")
        print(f"  💰 Budget: ${self.cost_tracker.budget:.2f}")
        print(f"{'='*60}\n")

        try:
            # Phase 2: Plan scenes (skips if scenes already exist)
            scene_plan = await self._plan_scenes()
            if not scene_plan:
                return self._handle_failure("Scene Planning", "Failed to generate scene plan")

            # Phase 3: Generate frames (skips scenes that already have images)
            frames_ok = await self._generate_frames()
            if not frames_ok:
                return self._handle_failure("Frame Generation", "Failed to generate frames")

            # Phase 4: Animate (skips scenes that already have video)
            animation_ok = await self._animate_scenes()

            # Phase 5: QC (skips scenes that already have qc_score)
            await self._run_qc()

            # Phase 6: Finalize
            summary = await self._finalize()
            return summary

        except Exception as e:
            return self._handle_failure("Pipeline", str(e))

    def _find_project(self) -> Optional[dict]:
        """Find one project to process — new or in-progress."""
        for status in self.RESUMABLE_STATUSES:
            projects = self.airtable.get_projects_by_status(status, limit=1)
            if projects:
                print(f"  Found project with Status = '{status}'")
                return projects[0]
        return None

    # ==================== PHASE 2: SCENE PLANNING ====================

    async def _plan_scenes(self) -> Optional[dict]:
        """Generate scene plan and write to Airtable. Skips if scenes already exist."""
        print("  📋 Phase 2: Scene Planning")

        # Check if scenes already exist (resume case)
        existing_scenes = self.airtable.get_scenes_for_project(self.project_name)
        if existing_scenes:
            print(f"    ✅ {len(existing_scenes)} scenes already exist, skipping planning")
            # Build a minimal scene_plan dict for downstream use
            scene_plan = {
                "scenes": existing_scenes,
                "total_scenes": len(existing_scenes),
            }
            return scene_plan

        self.airtable.update_project_status(
            self.current_project["id"],
            PROJECT_STATUS_PLANNING,
        )

        script = self.current_project.get("script", "")
        creative_direction = self.current_project.get("Creative Direction", "")
        core_elements = self.current_project.get("Core Elements", "")
        video_title = self.project_name

        if not script:
            print("    ❌ No script found in project record")
            return None

        # Generate scene plan via Sonnet
        scene_plan = await self.planner.plan_scenes(
            script=script,
            creative_direction=creative_direction,
            core_elements=core_elements,
            video_title=video_title,
        )

        # Convert to Airtable rows and write
        rows = self.planner.scenes_to_airtable_rows(scene_plan, self.project_name)

        print(f"    📝 Writing {len(rows)} scenes to Airtable...")
        for i, row in enumerate(rows):
            self.airtable.create_scene(row)
            if (i + 1) % 10 == 0:
                print(f"    ... {i + 1}/{len(rows)} scenes written")

        print(f"    ✅ All {len(rows)} scenes written to Airtable")

        # Update project fields
        scenes = scene_plan.get("scenes", [])
        animated = sum(1 for s in scenes if s.get("scene_type") == "animated")
        ken_burns = sum(1 for s in scenes if s.get("scene_type") == "ken_burns")
        static = sum(1 for s in scenes if s.get("scene_type") == "static")

        glow_curve = json.dumps(scene_plan.get("glow_curve", []))
        self.airtable.update_project_fields(self.current_project["id"], {
            "total_scenes": len(scenes),
            "glow_curve": glow_curve,
            "production_type": "animated",
        })

        # Notify
        estimated_cost = scene_plan.get("estimated_animation_cost", 0)
        self.notifier.notify_scene_planning_done(
            self.project_name,
            len(scenes),
            animated,
            ken_burns,
            static,
            estimated_cost,
        )

        return scene_plan

    # ==================== PHASE 3: FRAME GENERATION ====================

    async def _generate_frames(self) -> bool:
        """Generate start and end frame images for all scenes."""
        print("\n  🖼️ Phase 3: Frame Generation")

        self.airtable.update_project_status(
            self.current_project["id"],
            PROJECT_STATUS_GENERATING_FRAMES,
        )

        scenes = self.airtable.get_scenes_needing_images(self.project_name)
        total = len(scenes)
        print(f"    {total} scenes need frame generation")

        if total == 0:
            print("    ✅ All scenes already have images")
            return True

        success_count = 0
        for i, scene in enumerate(scenes):
            scene_order = scene.get("scene_order", i + 1)
            scene_type = scene.get("scene_type", "animated")
            record_id = scene["id"]

            print(f"\n    --- Scene {scene_order} ({scene_type}) [{i+1}/{total}] ---")

            # Budget check
            if not self.cost_tracker.can_afford_scene(scene_type):
                print(f"    🛑 Budget exceeded, stopping frame generation")
                self.notifier.notify_budget_exceeded(
                    self.project_name,
                    self.cost_tracker.total_spend,
                    self.cost_tracker.budget,
                )
                self.airtable.update_project_status(
                    self.current_project["id"],
                    PROJECT_STATUS_BUDGET_EXCEEDED,
                )
                return False

            start_prompt = scene.get("start_image_prompt", "")
            end_prompt = scene.get("end_image_prompt", "")

            if not start_prompt:
                print(f"    ⚠️ No start_image_prompt, skipping")
                continue

            # For ken_burns and static, we only need start frame
            if scene_type in ("ken_burns", "static"):
                start_url = await self.image_gen.generate_frame(start_prompt)
                if start_url:
                    self.cost_tracker.record_image_cost(scene_order)
                    # Use start image as both start and end for non-animated
                    self.airtable.update_scene_images(record_id, start_url, start_url)
                    self.airtable.update_scene(record_id, {"scene_cost": self.cost_tracker.get_scene_cost(scene_order)})
                    success_count += 1
                else:
                    print(f"    ❌ Failed to generate image for scene {scene_order}")
                continue

            # Animated scenes need both start and end frames
            if not end_prompt:
                print(f"    ⚠️ No end_image_prompt for animated scene, using start prompt")
                end_prompt = start_prompt

            start_url, end_url = await self.image_gen.generate_frame_pair(
                start_prompt, end_prompt,
            )

            if start_url and end_url:
                self.cost_tracker.record_image_cost(scene_order)
                self.cost_tracker.record_image_cost(scene_order)
                self.airtable.update_scene_images(record_id, start_url, end_url)
                self.airtable.update_scene(record_id, {"scene_cost": self.cost_tracker.get_scene_cost(scene_order)})
                success_count += 1
            else:
                print(f"    ❌ Failed to generate frame pair for scene {scene_order}")

            # Budget alert check
            if self.cost_tracker.budget_alert:
                scenes_remaining = total - (i + 1)
                self.notifier.notify_budget_alert(
                    self.project_name,
                    self.cost_tracker.total_spend,
                    self.cost_tracker.budget,
                    scenes_remaining,
                )

        print(f"\n    ✅ Frame generation complete: {success_count}/{total} scenes")
        self.notifier.notify_frames_done(self.project_name, success_count)
        return success_count > 0

    # ==================== PHASE 4: ANIMATION ====================

    async def _animate_scenes(self) -> bool:
        """Submit animated scenes to Veo 3.1 Fast."""
        print("\n  🎬 Phase 4: Animation")

        self.airtable.update_project_status(
            self.current_project["id"],
            PROJECT_STATUS_ANIMATING,
        )

        scenes = self.airtable.get_scenes_needing_animation(self.project_name)
        total = len(scenes)
        print(f"    {total} animated scenes need video generation")

        if total == 0:
            print("    ✅ All animated scenes already have video")
            return True

        success_count = 0
        for i, scene in enumerate(scenes):
            scene_order = scene.get("scene_order", i + 1)
            record_id = scene["id"]
            regen_count = scene.get("regen_count", 0)

            print(f"\n    --- Scene {scene_order} (animated) [{i+1}/{total}] ---")

            # Budget check
            if self.cost_tracker.budget_exceeded:
                print(f"    🛑 Budget exceeded, stopping animation")
                self.notifier.notify_budget_exceeded(
                    self.project_name,
                    self.cost_tracker.total_spend,
                    self.cost_tracker.budget,
                )
                self.airtable.update_project_status(
                    self.current_project["id"],
                    PROJECT_STATUS_BUDGET_EXCEEDED,
                )
                return False

            # Get image URLs from attachments
            start_images = scene.get("start_image", [])
            end_images = scene.get("end_image", [])

            if not start_images or not end_images:
                print(f"    ⚠️ Missing images for scene {scene_order}, skipping")
                continue

            start_url = start_images[0].get("url", "")
            end_url = end_images[0].get("url", "")
            motion_desc = scene.get("motion_description", "Smooth camera movement between frames")

            video_url = await self.animator.animate_scene(
                start_image_url=start_url,
                end_image_url=end_url,
                motion_description=motion_desc,
            )

            if video_url:
                self.cost_tracker.record_animation_cost(scene_order)
                self.airtable.update_scene_video(record_id, video_url)
                self.airtable.update_scene(record_id, {"scene_cost": self.cost_tracker.get_scene_cost(scene_order)})
                success_count += 1
            else:
                # Handle failure with retry logic
                if regen_count < MAX_REGEN_ATTEMPTS:
                    self.airtable.increment_regen_count(record_id, regen_count)
                    print(f"    ⚠️ Scene {scene_order} failed, will retry (attempt {regen_count + 1}/{MAX_REGEN_ATTEMPTS})")
                else:
                    print(f"    ❌ Scene {scene_order} failed after {MAX_REGEN_ATTEMPTS} attempts, flagging for manual review")

            # Progress notification every 10 scenes
            if (i + 1) % 10 == 0:
                self.notifier.notify_animation_progress(
                    self.project_name,
                    success_count,
                    total,
                    self.cost_tracker.total_spend,
                )

        print(f"\n    ✅ Animation complete: {success_count}/{total} clips generated")
        return success_count > 0

    # ==================== PHASE 5: QC ====================

    async def _run_qc(self):
        """Run quality checks on completed animated clips."""
        print("\n  🔍 Phase 5: Quality Check")

        self.airtable.update_project_status(
            self.current_project["id"],
            PROJECT_STATUS_QC,
        )

        scenes = self.airtable.get_scenes_needing_qc(self.project_name)
        total = len(scenes)
        print(f"    {total} scenes need QC")

        if total == 0:
            print("    ✅ All scenes already have QC scores")
            return

        failed_scenes = []

        for i, scene in enumerate(scenes):
            scene_order = scene.get("scene_order", i + 1)
            record_id = scene["id"]
            regen_count = scene.get("regen_count", 0)

            print(f"\n    --- QC Scene {scene_order} [{i+1}/{total}] ---")

            start_images = scene.get("start_image", [])
            end_images = scene.get("end_image", [])
            video_attachments = scene.get("scene_video", [])

            start_url = start_images[0].get("url", "") if start_images else ""
            end_url = end_images[0].get("url", "") if end_images else ""
            video_url = video_attachments[0].get("url", "") if video_attachments else ""

            glow_state = scene.get("glow_state", 50)
            color_temp = scene.get("color_temperature", "neutral")
            motion_desc = scene.get("motion_description", "")

            result = await self.qc.check_scene(
                start_image_url=start_url,
                end_image_url=end_url,
                video_url=video_url,
                glow_state=glow_state,
                color_temperature=color_temp,
                motion_description=motion_desc,
            )

            # Write QC results
            self.airtable.update_scene_qc(
                record_id,
                qc_score=result["qc_score"],
                qc_notes=result["notes"],
            )

            # Handle QC failures
            if not result["pass"]:
                if regen_count < MAX_REGEN_ATTEMPTS:
                    # Reset for regeneration
                    self.airtable.increment_regen_count(record_id, regen_count)
                    self.airtable.reset_scene_for_regen(record_id)
                    print(f"    ⚠️ Scene {scene_order} failed QC, queued for regen (attempt {regen_count + 1}/{MAX_REGEN_ATTEMPTS})")
                else:
                    failed_scenes.append({
                        "scene_order": scene_order,
                        "qc_score": result["qc_score"],
                        "qc_notes": result["notes"],
                    })
                    print(f"    ❌ Scene {scene_order} failed QC after max retries, flagging for manual review")

        if failed_scenes:
            self.notifier.notify_qc_failures(self.project_name, failed_scenes)

        print(f"\n    ✅ QC complete. {len(failed_scenes)} scenes need manual review.")

    # ==================== PHASE 6: FINALIZE ====================

    async def _finalize(self) -> dict:
        """Calculate final costs, update project status, and notify."""
        print("\n  🏁 Phase 6: Finalize")

        # Count completed scenes
        completed = self.airtable.get_completed_scenes_count(self.project_name)
        all_scenes = self.airtable.get_scenes_for_project(self.project_name)
        total = len(all_scenes)

        # Count failures (scenes where video done = false and regen_count >= MAX)
        failures = sum(
            1 for s in all_scenes
            if not s.get("video done") and s.get("regen_count", 0) >= MAX_REGEN_ATTEMPTS
            and s.get("scene_type") == "animated"
        )

        # Update project
        cost_summary = self.cost_tracker.summary()
        self.airtable.update_project_fields(self.current_project["id"], {
            "animation_spend": cost_summary["total_spend"],
            "scenes_complete": completed,
            "Status": PROJECT_STATUS_DONE,
        })

        # Notify
        self.notifier.notify_pipeline_complete(
            self.project_name,
            total,
            completed,
            cost_summary["total_spend"],
            failures,
        )

        summary = {
            "project_name": self.project_name,
            "total_scenes": total,
            "scenes_complete": completed,
            "failures": failures,
            **cost_summary,
        }

        print(f"\n  {'='*60}")
        print(f"  ✅ Animation Pipeline Complete: {self.project_name}")
        print(f"     Scenes: {completed}/{total}")
        print(f"     Cost:   ${cost_summary['total_spend']:.2f} / ${cost_summary['budget']:.2f}")
        print(f"     Failures: {failures}")
        print(f"  {'='*60}\n")

        return summary

    def _handle_failure(self, step: str, error: str) -> dict:
        """Handle a pipeline failure."""
        print(f"\n  ❌ Pipeline failed at {step}: {error}")

        if self.current_project:
            self.airtable.update_project_status(
                self.current_project["id"],
                PROJECT_STATUS_FAILED,
            )

        self.notifier.notify_error(
            self.project_name or "Unknown",
            step,
            error,
        )

        return {
            "project_name": self.project_name,
            "status": "failed",
            "failed_at": step,
            "error": error,
        }


async def main():
    """Entry point for the animation pipeline."""
    pipeline = AnimationPipeline()
    result = await pipeline.run()

    if result:
        print(f"\nResult: {json.dumps(result, indent=2)}")
    else:
        print("\nNo projects to process.")


if __name__ == "__main__":
    asyncio.run(main())
