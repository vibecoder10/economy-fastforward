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
    Step 3: Scene Expansion (~120-150 concepts)
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
from .script_generator import generate_script, verify_script_claims
from .scene_expander import expand_scene_concepts
from .scene_validator import validate_scene_list, auto_fix_minor_issues, check_entity_consistency
from .pipeline_writer import graduate_to_pipeline, select_video_title, build_sources_list
from .psych_angle_assigner import (
    assign_angles_to_scenes,
    format_psych_arc_summary,
)
from .script_generator import extract_framework_from_script

try:
    from script_profiles import load_script_profile
except ImportError:
    load_script_profile = None

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
        total_images: int = 25,
        scene_output_dir: Optional[str] = None,
        script_model: str = "claude-sonnet-4-5-20250929",
        video_config=None,
    ):
        """Initialize the translator.

        Args:
            anthropic_client: AnthropicClient instance for LLM calls
            airtable_client: AirtableClient instance for database ops
            slack_client: SlackClient instance for notifications (optional)
            total_images: Target number of scenes (unused, kept for compat)
            scene_output_dir: Directory for scene JSON files
            script_model: Model for script generation (Opus for quality, Sonnet for cost)
            video_config: VideoConfig for dynamic word counts and act structure
        """
        self.anthropic = anthropic_client
        self.airtable = airtable_client
        self.slack = slack_client
        self.total_images = total_images or 25
        self.scene_output_dir = scene_output_dir
        self.script_model = script_model
        self.video_config = video_config

        # Load script profile (editorial voice, validation thresholds)
        self.profile = None
        if load_script_profile is not None:
            try:
                self.profile = load_script_profile()
                if self.profile:
                    logger.info(
                        f"Script profile loaded: {self.profile.profile_id}"
                    )
            except Exception as e:
                logger.warning(f"Could not load script profile: {e}")

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
            if self.video_config:
                dur = self.video_config.video_length_minutes
                self._notify(f"📝 Generating {dur}-minute narration script...")
            else:
                self._notify("📝 Generating narration script...")

            if self.profile:
                self._notify(
                    f"🎭 Profile: {self.profile.profile_id} "
                    f"(v{self.profile.version})"
                )
            script_result = await generate_script(
                self.anthropic, brief, model=self.script_model,
                config=self.video_config,
                profile=self.profile,
            )
            script = script_result["script"]
            result["script_validation"] = script_result["validation"]

            # --- PERSIST SCRIPT IMMEDIATELY (before validation/expansion) ---
            self._save_script_to_ideas(idea_record_id, script)

            # --- VALIDATION IS ADVISORY — report to Airtable + Slack, never block ---
            word_count = script_result["validation"]["word_count"]
            act_count = script_result["validation"]["act_count"]
            issues = script_result["validation"].get("issues", [])

            logger.info(f"Script generated: {word_count} words, {act_count} acts")

            if issues:
                logger.warning(f"Script validation issues (advisory): {issues}")

            # Editorial validation results (already run inside generate_script)
            editorial = script_result["validation"].get("editorial", {})
            editorial_summary = self._build_editorial_summary(editorial)

            # Persist editorial results immediately
            if editorial:
                self._write_editorial_to_ideas(idea_record_id, editorial_summary)

            # Build Slack quality report
            editorial_passed = editorial.get("passed", True) if editorial else True
            if not editorial_passed:
                failed_details = [
                    f"{c['name']}: {c['detail']}"
                    for c in editorial.get("checks", [])
                    if not c["passed"]
                ]
                self._notify(
                    f"📋 Script quality report for "
                    f"'{brief.get('headline', 'Untitled')}' "
                    f"({word_count} words, {act_count} acts):\n"
                    f"{chr(10).join(failed_details)}\n"
                    f"Pipeline continues — review Script Validation field."
                )
            else:
                logger.info("Editorial validation: all checks passed")

            # === STEP 2a: Extract and persist framework ===
            selected_framework = extract_framework_from_script(script)
            if not selected_framework:
                # Fallback: use the framework_angle from the research brief
                selected_framework = brief.get("framework_angle", "")
            if selected_framework:
                logger.info(f"Selected framework: {selected_framework}")
                brief["_selected_framework"] = selected_framework
                # Write to Airtable "Framework Angle" field (graceful degradation)
                try:
                    self.airtable.update_idea_fields(
                        idea_record_id, {"Framework Angle": selected_framework}
                    )
                except Exception as fw_err:
                    logger.warning(
                        f"Could not write Framework Angle to Airtable: {fw_err}"
                    )
                    self._notify(f"⚠️ Framework Angle write failed: {fw_err}")
            else:
                logger.info("No framework found in script output or research brief")

            # === STEP 2b: Entity consistency check ===
            entity_warnings = check_entity_consistency(
                script=script,
                brief=brief,
                slack_client=self.slack,
                video_title=brief.get("headline", ""),
            )
            if entity_warnings:
                logger.warning(
                    f"Entity consistency: {len(entity_warnings)} potential "
                    f"hallucination(s) detected"
                )

            # === STEP 2c: Verify factual claims (non-blocking) ===
            unverified_claims = ""
            try:
                unverified_claims = await verify_script_claims(
                    self.anthropic, script, brief
                )
                if unverified_claims:
                    logger.warning(
                        f"Claim verification flagged potential issues:\n"
                        f"{unverified_claims[:500]}"
                    )
                    self._notify(
                        f"⚠️ Claim verification flagged unverified claims "
                        f"for '{brief.get('headline', 'Untitled')}'. "
                        f"Check 'Unverified Claims' field in Script table."
                    )
                else:
                    logger.info("Claim verification: all claims grounded")
            except Exception as cv_err:
                logger.warning(
                    f"Claim verification skipped (non-blocking): {cv_err}"
                )

            # === STEP 2d: Assign Psychological Angles ===
            from .script_generator import extract_acts
            acts = extract_acts(script)
            if not acts:
                acts = {1: script}

            psych_angles_raw = brief.get("psychological_angles", "")
            psych_assignments = assign_angles_to_scenes(
                num_scenes=len(acts),
                psychological_angles=psych_angles_raw,
            )
            psych_arc_summary = format_psych_arc_summary(psych_assignments)
            if psych_arc_summary:
                logger.info(f"Psychological arc: {psych_arc_summary}")

            # === STEP 2e: Write Script records progressively ===
            # Write each act to the Scripts table BEFORE scene expansion so
            # records are saved even if expansion times out or fails.
            script_record_ids = self._write_script_records(
                acts=acts,
                brief=brief,
                psych_assignments=psych_assignments,
                unverified_claims=unverified_claims,
                editorial_summary=editorial_summary,
            )
            result["script_record_ids"] = script_record_ids

            # === STEP 3: Scene Expansion (per-scene concept expansion) ===
            logger.info("Step 3: Expanding script into visual concepts (scene by scene)...")
            self._notify(f"🎬 Expanding script scenes into visual concepts...")

            scenes = []
            visual_seeds = brief.get("visual_seeds", "")
            scene_counter = 0
            for act_num in sorted(acts.keys()):
                act_text = acts[act_num]
                scene_counter += 1
                concepts = await expand_scene_concepts(
                    anthropic_client=self.anthropic,
                    scene_number=scene_counter,
                    scene_text=act_text,
                    visual_seeds=visual_seeds,
                    accent_color="cold_teal",
                    act_number=act_num,
                    total_scenes=len(acts),
                )
                for c in concepts:
                    scenes.append({
                        "scene_number": scene_counter,
                        "concept_index": c["concept_index"],
                        "sentence_text": c["sentence_text"],
                        "visual_description": c["visual_description"],
                        "visual_style": c.get("visual_style", "dossier"),
                        "composition": c.get("composition", "medium"),
                        "mood": c.get("mood", ""),
                        "parent_act": act_num,
                    })

            logger.info(f"Expanded {len(acts)} acts into {len(scenes)} visual concepts")

            # === STEP 4: Pipeline Table Write ===
            logger.info("Step 4: Writing to pipeline...")
            self._notify("💾 Writing to pipeline table...")

            # editorial_summary was already built and written to Ideas table above

            graduation = await graduate_to_pipeline(
                airtable_client=self.airtable,
                idea_record_id=idea_record_id,
                brief=brief,
                script=script,
                scene_list=scenes,
                accent_color="cold_teal",
                scene_output_dir=self.scene_output_dir,
                slack_client=self.slack,
                acts=acts,
                psych_assignments=psych_assignments,
                unverified_claims=unverified_claims,
                editorial_validation=editorial_summary,
            )

            result["status"] = "success"
            result["pipeline_record_id"] = graduation["pipeline_record_id"]
            result["scene_filepath"] = graduation["scene_filepath"]
            result["video_id"] = graduation["video_id"]

            # Log framework + psychological arc to Slack
            framework_label = selected_framework or brief.get("framework_angle", "")
            if psych_arc_summary or framework_label:
                parts = ["📝 Script complete."]
                if framework_label:
                    parts.append(f"Framework: {framework_label}.")
                if psych_arc_summary:
                    parts.append(f"Psychological arc: {psych_arc_summary}")
                self._notify(" ".join(parts))

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

    def _save_script_to_ideas(self, idea_record_id: str, script: str):
        """Persist script text to the Ideas table immediately after generation.

        This ensures the script is saved even if validation, scene expansion,
        or downstream steps fail or time out.
        """
        if not script:
            return
        try:
            self.airtable.update_idea_fields(
                idea_record_id, {"Script": script}
            )
            logger.info("Script saved to Ideas table")
        except Exception as e:
            logger.warning(f"Could not save script to Ideas: {e}")
            self._notify(f"⚠️ Script field write failed: {e}")

    def _build_editorial_summary(self, editorial: dict) -> str:
        """Build editorial validation summary string from result dict."""
        if not editorial or not editorial.get("checks"):
            return ""
        overall = "PASSED" if editorial.get("passed", True) else "FAILED"
        lines = [f"Editorial validation: {overall}"]
        for c in editorial.get("checks", []):
            status = "PASS" if c["passed"] else "FAIL"
            lines.append(f"[{status}] {c['name']}: {c['detail']}")
        if self.profile:
            lines.append(f"Profile: {self.profile.profile_id}")
        retries = editorial.get("retries_used", 0)
        if retries:
            lines.append(f"Retries used: {retries}")
        return "\n".join(lines)

    def _write_editorial_to_ideas(self, idea_record_id: str, summary: str):
        """Write editorial validation summary to the Ideas table.

        This writes to the Ideas table (not Scripts) so it persists even
        when the pipeline blocks and no script records are created.
        """
        if not summary:
            return
        try:
            self.airtable.update_idea_fields(
                idea_record_id, {"Script Validation": summary}
            )
        except Exception as e:
            logger.warning(f"Could not write Script Validation to Ideas: {e}")
            self._notify(
                f"⚠️ Script Validation field write failed: {e}"
            )

    def _write_script_records(
        self,
        acts: dict,
        brief: dict,
        psych_assignments: list | None = None,
        unverified_claims: str = "",
        editorial_summary: str = "",
    ) -> list[str]:
        """Write script records to the Scripts table progressively (one per act).

        Called BEFORE scene expansion so records exist even if expansion
        times out or fails. Returns list of created record IDs.
        """
        video_title = select_video_title(brief)
        sources_text = build_sources_list(brief)

        angle_lookup = {}
        if psych_assignments:
            for pa in psych_assignments:
                angle_lookup[pa["scene"]] = pa["angle"]

        record_ids: list[str] = []
        first_record_id = None

        for act_num in sorted(acts.keys()):
            act_text = acts[act_num]
            psych_angle = angle_lookup.get(act_num, "")
            try:
                record = self.airtable.create_script_record(
                    scene_number=act_num,
                    scene_text=act_text,
                    title=video_title,
                    psych_angle=psych_angle,
                    sources=sources_text if act_num == 1 else "",
                )
                rid = record.get("id", "")
                record_ids.append(rid)
                if act_num == min(acts.keys()):
                    first_record_id = rid
                logger.info(f"Script record written: act {act_num}")
            except Exception as e:
                logger.error(f"Failed to write Script record for act {act_num}: {e}")
                self._notify(
                    f"⚠️ Script record write FAILED for act {act_num}: {e}"
                )

        # Write unverified claims to the first script record
        if unverified_claims and first_record_id:
            try:
                self.airtable.update_script_record(
                    first_record_id,
                    {"Unverified Claims": unverified_claims},
                )
            except Exception as e:
                logger.warning(f"Could not write Unverified Claims: {e}")
                self._notify(f"⚠️ Unverified Claims write failed: {e}")

        # Write editorial validation to the first script record
        if editorial_summary and first_record_id:
            try:
                self.airtable.update_script_record(
                    first_record_id,
                    {"Script Validation": editorial_summary},
                )
            except Exception as e:
                logger.warning(f"Could not write Script Validation to Script table: {e}")
                self._notify(f"⚠️ Script Validation write (Script table) failed: {e}")

        return record_ids

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
    total_images: int = 25,
    scene_output_dir: Optional[str] = None,
    script_model: str = "claude-sonnet-4-5-20250929",
    video_config=None,
) -> dict:
    """Convenience function to run the full translation pipeline.

    This is the main entry point for external callers.
    """
    translator = BriefTranslator(
        anthropic_client=anthropic_client,
        airtable_client=airtable_client,
        slack_client=slack_client,
        total_images=total_images,
        scene_output_dir=scene_output_dir,
        script_model=script_model,
        video_config=video_config,
    )
    return await translator.translate(idea_record_id, brief)
