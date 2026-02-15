"""Brief-to-Script Translation Layer.

Middleware that bridges the Research Agent's Ideas Bank output with the
video production pipeline. Transforms analytical research briefs into
production-ready creative assets.

Deep research is handled by the standalone research_agent module
(research_agent.py). This module consumes its output and handles:

Pipeline:
    Step 0: Deep Research (via research_agent.ResearchAgent — standalone module)
    Step 1: Production Readiness Validation
    Step 1b: Supplemental Research — targeted gap-filling (if needed)
    Step 2: Script Generation
    Step 3: Scene Expansion (~140 scenes)
    Step 4: Pipeline Table Write
"""

import asyncio
import json
import logging
from typing import Optional

from .validator import validate_brief, evaluate_validation, format_validation_summary
from .supplementer import (
    run_supplemental_research,
    merge_supplement_into_brief,
    MAX_SUPPLEMENT_PASSES,
)
from .script_generator import generate_script
from .scene_expander import expand_scenes, DEFAULT_TOTAL_SCENES, DEFAULT_TOTAL_IMAGES
from .scene_validator import validate_scene_list, auto_fix_minor_issues
from .pipeline_writer import graduate_to_pipeline

logger = logging.getLogger(__name__)


class BriefTranslator:
    """Orchestrates the full brief-to-pipeline translation process.

    Usage:
        translator = BriefTranslator(anthropic_client, airtable_client, slack_client)
        result = await translator.translate(idea_record_id, brief)
    """

    def __init__(
        self,
        anthropic_client,
        airtable_client,
        slack_client=None,
        accent_color: str = "cold_teal",
        total_images: int = DEFAULT_TOTAL_IMAGES,
        scene_output_dir: Optional[str] = None,
        script_model: str = "claude-sonnet-4-5-20250929",
    ):
        """Initialize the translator.

        Args:
            anthropic_client: AnthropicClient instance for LLM calls
            airtable_client: AirtableClient instance for database ops
            slack_client: SlackClient instance for notifications (optional)
            accent_color: Visual accent color (cold_teal | warm_amber | muted_crimson)
            total_images: Target number of scenes (~136-140)
            scene_output_dir: Directory for scene JSON files
            script_model: Model for script generation (Opus for quality, Sonnet for cost)
        """
        self.anthropic = anthropic_client
        self.airtable = airtable_client
        self.slack = slack_client
        self.accent_color = accent_color
        self.total_images = total_images
        self.scene_output_dir = scene_output_dir
        self.script_model = script_model

    async def translate(
        self,
        idea_record_id: str,
        brief: dict,
    ) -> dict:
        """Run the full translation pipeline.

        Args:
            idea_record_id: Airtable record ID from the Ideas Bank
            brief: Research brief dict with all fields from the Ideas Bank

        Returns:
            {
                "status": "success" | "rejected" | "error",
                "pipeline_record_id": str (if success),
                "scene_filepath": str (if success),
                "video_id": str (if success),
                "validation": dict,
                "script_validation": dict,
                "scene_validation": dict,
                "error": str (if error),
            }
        """
        result = {
            "status": "error",
            "idea_record_id": idea_record_id,
        }

        try:
            # === STEP 1: Production Readiness Validation ===
            logger.info("Step 1: Validating production readiness...")
            self._notify(f"🔍 Validating brief: {brief.get('headline', 'Untitled')}")

            validation = await validate_brief(self.anthropic, brief)
            result["validation"] = validation
            logger.info(format_validation_summary(validation))

            # Handle validation result
            if validation["decision"] == "REJECT":
                logger.warning("Brief rejected — insufficient material")
                self._notify(
                    f"❌ Brief rejected: {brief.get('headline', 'Untitled')}\n"
                    f"Reason: {validation.get('gaps', 'Multiple criteria failed')}"
                )
                self._mark_rejected(idea_record_id, validation)
                result["status"] = "rejected"
                return result

            # === STEP 1b: Supplemental Research (if needed) ===
            if validation["decision"] == "NEEDS_SUPPLEMENT":
                brief = await self._run_supplement_loop(brief, validation)
                if brief is None:
                    # Supplement loop exhausted, still failing
                    logger.warning("Brief still failing after supplemental research")
                    self._mark_rejected(idea_record_id, validation)
                    result["status"] = "rejected"
                    return result

            # === STEP 2: Script Generation ===
            logger.info("Step 2: Generating script...")
            self._notify("📝 Generating 25-minute narration script...")

            script_result = await generate_script(
                self.anthropic, brief, model=self.script_model
            )
            script = script_result["script"]
            result["script_validation"] = script_result["validation"]

            if not script_result["validation"]["valid"]:
                issues = script_result["validation"]["issues"]
                logger.warning(f"Script validation issues: {issues}")
                # Continue if the issues are minor (word count slightly off)
                # but fail on structural issues
                if script_result["validation"]["act_count"] < 6:
                    result["error"] = f"Script generation failed: {issues}"
                    self._notify(f"❌ Script failed: {issues}")
                    return result

            logger.info(
                f"Script generated: {script_result['validation']['word_count']} words, "
                f"{script_result['validation']['act_count']} acts"
            )

            # === STEP 3: Scene Expansion (6 Acts → 20-30 Scenes) ===
            logger.info("Step 3: Expanding script into production scenes...")
            self._notify(f"🎬 Expanding to ~{self.total_images} production scenes...")

            scenes = await expand_scenes(
                self.anthropic,
                script,
                brief.get("visual_seeds", ""),
                self.accent_color,
                self.total_images,
            )

            # Validate scene list
            scene_validation = validate_scene_list(
                scenes, {"total_images": self.total_images}
            )
            result["scene_validation"] = scene_validation

            if not scene_validation["valid"]:
                logger.info(
                    f"Scene validation found {scene_validation['issue_count']} issues, "
                    f"attempting auto-fix..."
                )
                scenes = auto_fix_minor_issues(scenes)
                scene_validation = validate_scene_list(
                    scenes, {"total_images": self.total_images}
                )
                result["scene_validation"] = scene_validation

                if not scene_validation["valid"]:
                    # Try one more expansion with error feedback
                    major_issues = [
                        i for i in scene_validation["issues"]
                        if "Too few" in i or "missing field" in i
                    ]
                    if major_issues:
                        logger.warning(f"Major scene issues remain: {major_issues}")
                        result["error"] = f"Scene expansion failed: {major_issues}"
                        self._notify(f"❌ Scene expansion failed: {major_issues}")
                        return result
                    # Minor issues only — proceed with warning
                    logger.warning(
                        f"Proceeding with {scene_validation['issue_count']} minor scene issues"
                    )

            logger.info(
                f"Scenes expanded: {scene_validation['stats']['total_scenes']} scenes | "
                f"D:{scene_validation['stats']['dossier']} "
                f"S:{scene_validation['stats']['schema']} "
                f"E:{scene_validation['stats']['echo']}"
            )

            # === STEP 4: Pipeline Table Write ===
            logger.info("Step 4: Writing to pipeline...")
            self._notify("💾 Writing to pipeline table...")

            graduation = await graduate_to_pipeline(
                airtable_client=self.airtable,
                idea_record_id=idea_record_id,
                brief=brief,
                script=script,
                scene_list=scenes,
                accent_color=self.accent_color,
                scene_output_dir=self.scene_output_dir,
                slack_client=self.slack,
            )

            result["status"] = "success"
            result["pipeline_record_id"] = graduation["pipeline_record_id"]
            result["scene_filepath"] = graduation["scene_filepath"]
            result["video_id"] = graduation["video_id"]

            logger.info(
                f"Translation complete: {graduation['video_id']} → "
                f"{graduation['pipeline_record_id']}"
            )

            return result

        except Exception as e:
            logger.exception("Translation pipeline failed")
            result["error"] = str(e)
            self._notify(
                f"❌ Pipeline failed for {brief.get('headline', 'Untitled')}: {e}"
            )
            return result

    async def _run_supplement_loop(self, brief: dict, validation: dict) -> Optional[dict]:
        """Run supplemental research loop up to MAX_SUPPLEMENT_PASSES times.

        Returns:
            Updated brief if validation passes, None if all attempts exhausted.
        """
        current_brief = brief

        for attempt in range(1, MAX_SUPPLEMENT_PASSES + 1):
            logger.info(f"Step 1b: Supplemental research (attempt {attempt}/{MAX_SUPPLEMENT_PASSES})...")
            self._notify(f"🔬 Running supplemental research (attempt {attempt})...")

            supplement_text = await run_supplemental_research(
                self.anthropic, current_brief, validation["gaps"]
            )

            current_brief = merge_supplement_into_brief(
                current_brief, supplement_text, validation["gaps"]
            )

            # Re-validate
            validation = await validate_brief(self.anthropic, current_brief)
            logger.info(format_validation_summary(validation))

            if validation["decision"] == "READY":
                return current_brief

            if validation["decision"] == "REJECT":
                return None

        # Exhausted all attempts
        return None

    def _notify(self, message: str):
        """Send a Slack notification if client is available."""
        if self.slack:
            try:
                self.slack.send_message(message)
            except Exception:
                pass

    def _mark_rejected(self, idea_record_id: str, validation: dict):
        """Mark an Idea Concepts record as rejected."""
        try:
            self.airtable.update_idea_status(idea_record_id, "rejected")
        except Exception:
            try:
                self.airtable.idea_concepts_table.update(
                    idea_record_id,
                    {"Status": "rejected"},
                    typecast=True,
                )
            except Exception as e:
                logger.warning(f"Could not mark idea as rejected: {e}")

        # Add rejection reason as a note
        try:
            gaps = validation.get("gaps", "Multiple production criteria failed")
            self.airtable.update_idea_field(
                idea_record_id,
                "Idea Reasoning",
                f"Production validation failed: {gaps[:500]}",
            )
        except Exception:
            pass


async def translate_brief(
    anthropic_client,
    airtable_client,
    idea_record_id: str,
    brief: dict,
    slack_client=None,
    accent_color: str = "cold_teal",
    total_images: int = DEFAULT_TOTAL_IMAGES,
    scene_output_dir: Optional[str] = None,
    script_model: str = "claude-sonnet-4-5-20250929",
) -> dict:
    """Convenience function to run the full translation pipeline.

    This is the main entry point for external callers.
    """
    translator = BriefTranslator(
        anthropic_client=anthropic_client,
        airtable_client=airtable_client,
        slack_client=slack_client,
        accent_color=accent_color,
        total_images=total_images,
        scene_output_dir=scene_output_dir,
        script_model=script_model,
    )
    return await translator.translate(idea_record_id, brief)
