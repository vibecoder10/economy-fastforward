"""Brief-to-Script Translation Layer.

Middleware that bridges the Research Agent's Ideas Bank output with the
video production pipeline. Transforms analytical research briefs into
production-ready scripts.

Deep research is handled by the standalone research_agent module
(research_agent.py). This module consumes its output and handles:

Pipeline:
    Step 0: Deep Research (via research_agent.ResearchAgent — standalone module)
    Step 1: Production Readiness Validation
    Step 1b: Supplemental Research — targeted gap-filling (if needed)
    Step 2: Script Generation + Airtable/Drive/Slack writes

Scene expansion is a SEPARATE pipeline stage triggered by a different status.
"""

from __future__ import annotations

import logging
from typing import Optional

from .validator import validate_brief, evaluate_validation, format_validation_summary
from .supplementer import (
    run_supplemental_research,
    merge_supplement_into_brief,
    MAX_SUPPLEMENT_PASSES,
)
from .script_generator import generate_script, verify_script_claims, extract_acts
from .scene_validator import check_entity_consistency
from .pipeline_writer import select_video_title, build_sources_list
from .psych_angle_assigner import (
    assign_angles_to_scenes,
    format_psych_arc_summary,
)
from .script_generator import extract_framework_from_script
from .script_validator import (
    validate_script_editorial,
    ScriptValidationConfig,
    ScriptValidationResult,
)
from .senior_editor import run_senior_editor, format_editor_summary
from orchestrator.pipeline_constants import IdeaFields, Models, Statuses

try:
    from shared.profiles.script import load_script_profile
except ImportError:
    load_script_profile = None

logger = logging.getLogger(__name__)


class BriefTranslator:
    """Orchestrates script generation from a research brief.

    Generates the script, saves it to Airtable and Google Drive, runs
    advisory validation, and writes results. Does NOT run scene expansion
    — that is a separate pipeline stage.

    Usage:
        translator = BriefTranslator(anthropic_client, airtable_client, slack_client)
        result = await translator.translate(idea_record_id, brief)
    """

    def __init__(
        self,
        anthropic_client,
        airtable_client,
        slack_client=None,
        google_client=None,
        script_model: str = Models.CLAUDE_SONNET,
        video_config=None,
        script_system_prompt_override: Optional[str] = None,
    ):
        self.anthropic = anthropic_client
        self.airtable = airtable_client
        self.slack = slack_client
        self.google = google_client
        self.script_model = script_model
        self.video_config = video_config
        self.script_system_prompt_override = script_system_prompt_override

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
        project_folder_id: str = None,
    ) -> dict:
        """Generate a script and save to Airtable + Google Drive.

        This is script generation ONLY. Scene expansion is a separate
        pipeline stage triggered by a different status.

        Steps:
            1. Validate brief
            2. Generate script (single LLM call)
            3. Save script to Airtable Script field
            4. Save script to Google Drive as a Doc
            5. Run editorial validation (advisory, no retries)
            6. Write validation results to Script Validation field
            7. Write Script table records (one per act)
            8. Entity check + claim verification (non-blocking)

        Returns:
            {
                "status": "success" | "rejected" | "error",
                "script": str,
                "validation": dict,
                "script_validation": dict,
                "doc_url": str (if Drive available),
                "error": str (if error),
            }
        """
        result = {
            "status": "error",
            "idea_record_id": idea_record_id,
        }

        try:
            # === STEP 1: Production Readiness Validation ===
            # The brief gate (validate_brief) is an LLM judge for DOCUMENTARY
            # research-brief depth (fact density, framework depth, supporting
            # evidence, …). It is opt-in per profile: only the Power-Doctrine
            # style requires it. When the active profile sets
            # validation.requires_research_brief=False (the neutral default),
            # a simple premise (ESL, cooking, a story) must proceed straight to
            # generation — it must NOT be rejected for lacking documentary
            # depth. If no profile loaded, preserve the legacy behavior and run
            # the gate.
            requires_brief_gate = (
                self.profile is None
                or self.profile.validation.requires_research_brief
            )

            if not requires_brief_gate:
                logger.info(
                    "Step 1: Brief gate SKIPPED — profile "
                    f"'{self.profile.profile_id}' does not require a research "
                    "brief (requires_research_brief=False); proceeding to "
                    "script generation."
                )
                validation = {
                    "decision": "READY",
                    "criteria": [],
                    "overall_verdict": "READY",
                    "gaps": "",
                    "skipped": True,
                }
                result["validation"] = validation
            else:
                logger.info("Step 1: Validating production readiness...")
                self._notify(
                    f"🔍 Validating brief: {brief.get('headline', 'Untitled')}"
                )

                validation = await validate_brief(self.anthropic, brief)
                result["validation"] = validation
                logger.info(format_validation_summary(validation))

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
                    logger.warning("Brief still failing after supplemental research")
                    self._mark_rejected(idea_record_id, validation)
                    result["status"] = "rejected"
                    return result

            # === STEP 2: Script Generation (single LLM call) ===
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
                system_prompt_override=self.script_system_prompt_override,
            )
            script = script_result["script"]
            result["script"] = script
            result["script_validation"] = script_result["validation"]

            word_count = script_result["validation"]["word_count"]
            act_count = script_result["validation"]["act_count"]
            logger.info(f"Script generated: {word_count} words, {act_count} acts")

            # === STEP 2b: Silent originality re-roll (anti-demonetization) ===
            # If this draft recycles a plot the channel already made, quietly
            # regenerate with a "completely different plot" nudge BEFORE we save,
            # show, or split it. Invisible to the creator, capped, fails open. The
            # backend passes recent plots via RECENT_PLOTS_JSON; the guard uses a
            # direct Sonnet call so it survives a Kie outage. See
            # shared/originality_guard.py.
            try:
                from shared.originality_guard import maybe_reroll_for_plot

                async def _regen(spo):
                    return await generate_script(
                        self.anthropic, brief, model=self.script_model,
                        config=self.video_config, profile=self.profile,
                        system_prompt_override=spo,
                    )

                script, script_result = await maybe_reroll_for_plot(
                    title=brief.get("video_title") or brief.get("headline") or "",
                    script=script,
                    script_result=script_result,
                    regenerate=_regen,
                    base_system_prompt=self.script_system_prompt_override or "",
                )
                result["script"] = script
                result["script_validation"] = script_result["validation"]
                word_count = script_result["validation"]["word_count"]
                act_count = script_result["validation"]["act_count"]
            except Exception as e:
                logger.warning(f"originality re-roll skipped: {e}")

            # === PROGRESSIVE WRITE: Save script immediately (never lose work) ===
            # Write to Airtable FIRST — fast, always available
            self._save_script_to_ideas(idea_record_id, script)

            # Write to Google Drive SECOND — slower but provides reviewer-friendly doc
            doc_url = self._save_script_to_drive(script, brief, project_folder_id)
            if doc_url:
                result["doc_url"] = doc_url
                logger.info(f"Script saved to Google Drive: {doc_url}")

            # === STEP 3: Blocking Validation (all 7 checks) ===
            acts = extract_acts(script)
            if not acts:
                acts = {1: script}

            editorial_config = (
                ScriptValidationConfig.from_profile(self.profile)
                if self.profile is not None
                else ScriptValidationConfig()
            )

            validation_result = validate_script_editorial(
                script=script, brief=brief, acts=acts, config=editorial_config
            )

            # === STEP 4: Senior Editor Pass (if validation failed) ===
            editor_result = None
            if not validation_result.passed:
                failed_names = [c.name for c in validation_result.failed_checks]
                logger.warning(
                    f"Validation failed ({len(failed_names)} checks): {failed_names}"
                )
                self._notify(
                    f"🔧 Running senior editor for "
                    f"'{brief.get('headline', 'Untitled')}' — "
                    f"fixing: {', '.join(failed_names)}"
                )

                editor_result = await run_senior_editor(
                    anthropic_client=self.anthropic,
                    script=script,
                    acts=acts,
                    failed_checks=validation_result.failed_checks,
                    brief=brief,
                    model=self.script_model,
                )

                if editor_result["success"] and editor_result["changelog"]:
                    # Update script with editor's changes
                    script = editor_result["script"]
                    result["script"] = script
                    result["editor_changelog"] = editor_result["changelog"]

                    # Re-extract acts from corrected script
                    acts = extract_acts(script)
                    if not acts:
                        acts = {1: script}

                    # Re-validate
                    validation_result = validate_script_editorial(
                        script=script, brief=brief, acts=acts, config=editorial_config
                    )

                    logger.info(format_editor_summary(editor_result))

            # === STEP 5: Block if Still Failing ===
            editorial_summary = self._build_editorial_summary(
                validation_result.to_dict()
            )

            if not validation_result.passed:
                # Pipeline BLOCKED — requires manual approval
                failed_names = [c.name for c in validation_result.failed_checks]
                failed_details = [
                    f"• {c.name}: {c.detail}"
                    for c in validation_result.failed_checks
                ]

                logger.error(
                    f"Script validation BLOCKED: {len(failed_names)} checks "
                    f"still failing after senior editor"
                )

                # Save script anyway (for review)
                self._save_script_to_ideas(idea_record_id, script)

                # Write validation results
                self._write_editorial_to_ideas(idea_record_id, editorial_summary)

                # Mark as needing review
                try:
                    self.airtable.update_idea_fields(
                        idea_record_id,
                        {"Status": Statuses.NEEDS_SCRIPT_REVIEW},
                    )
                except Exception:
                    pass  # Status field may not exist

                # Send blocking notification with script preview and approval prompt
                title = brief.get('headline', 'Untitled')
                script_preview = script[:800] + "..." if len(script) > 800 else script
                self._notify(
                    f"🚫 *SCRIPT BLOCKED:* '{title}'\n"
                    f"Senior editor could not fix {len(failed_names)} issue(s):\n"
                    f"{chr(10).join(failed_details)}\n\n"
                    f"*Script saved to Airtable for review.*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"*Script Preview:*\n```{script_preview}```\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📝 *To approve and continue:* Reply `approved` or `!approve {title[:30]}`"
                )

                result["status"] = "blocked"
                result["blocked_checks"] = failed_names
                result["validation_summary"] = editorial_summary
                return result

            # === Validation PASSED ===
            logger.info("Editorial validation: all checks passed")
            if editor_result and editor_result.get("changelog"):
                self._notify(
                    f"✅ Senior editor fixed script: "
                    f"'{brief.get('headline', 'Untitled')}'\n"
                    f"{format_editor_summary(editor_result)}"
                )

            # === STEP 6: Update script if senior editor made changes ===
            # (Original already saved before validation; this overwrites with fixes)
            if editor_result and editor_result.get("changelog"):
                self._save_script_to_ideas(idea_record_id, script)
                # Overwrite Drive doc with fixed version
                updated_doc_url = self._save_script_to_drive(script, brief, project_folder_id)
                if updated_doc_url:
                    result["doc_url"] = updated_doc_url

            # === STEP 7: Write validation results ===
            self._write_editorial_to_ideas(idea_record_id, editorial_summary)

            # === STEP 9: Extract framework, assign psych angles, write Script records ===
            selected_framework = extract_framework_from_script(script)
            if not selected_framework:
                selected_framework = brief.get("framework_angle", "")
            if selected_framework:
                logger.info(f"Selected framework: {selected_framework}")
                brief["_selected_framework"] = selected_framework
                try:
                    self.airtable.update_idea_fields(
                        idea_record_id, {IdeaFields.FRAMEWORK_ANGLE: selected_framework}
                    )
                except Exception as fw_err:
                    logger.warning(
                        f"Could not write Framework Angle to Airtable: {fw_err}"
                    )
                    self._notify(f"⚠️ Framework Angle write failed: {fw_err}")

            # Note: `acts` already extracted above during validation

            psych_angles_raw = brief.get("psychological_angles", "")
            psych_assignments = assign_angles_to_scenes(
                num_scenes=len(acts),
                psychological_angles=psych_angles_raw,
            )
            psych_arc_summary = format_psych_arc_summary(psych_assignments)
            if psych_arc_summary:
                logger.info(f"Psychological arc: {psych_arc_summary}")

            # Write Script table records (one per act)
            script_record_ids = self._write_script_records(
                acts=acts,
                brief=brief,
                psych_assignments=psych_assignments,
                unverified_claims="",  # Claims verified below (async)
                editorial_summary=editorial_summary,
            )
            result["script_record_ids"] = script_record_ids

            # === STEP 8: Entity check + claim verification (non-blocking) ===
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
                    # Write claims to first script record
                    if script_record_ids:
                        try:
                            self.airtable.update_script_record(
                                script_record_ids[0],
                                {"Unverified Claims": unverified_claims},
                            )
                        except Exception as e:
                            logger.warning(f"Could not write Unverified Claims: {e}")
                else:
                    logger.info("Claim verification: all claims grounded")
            except Exception as cv_err:
                logger.warning(
                    f"Claim verification skipped (non-blocking): {cv_err}"
                )

            # === Done — report success ===
            result["status"] = "success"

            framework_label = selected_framework or brief.get("framework_angle", "")
            parts = [f"📝 Script complete ({word_count} words, {act_count} acts)."]
            if framework_label:
                parts.append(f"Framework: {framework_label}.")
            if psych_arc_summary:
                parts.append(f"Psychological arc: {psych_arc_summary}")
            if doc_url:
                parts.append(f"📄 {doc_url}")
            self._notify(" ".join(parts))

            return result

        except Exception as e:
            logger.exception("Translation pipeline failed")
            result["error"] = str(e)
            self._notify(
                f"❌ Pipeline failed for {brief.get('headline', 'Untitled')}: {e}"
            )
            return result

    async def _run_supplement_loop(self, brief: dict, validation: dict) -> Optional[dict]:
        """Run supplemental research loop up to MAX_SUPPLEMENT_PASSES times."""
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

            validation = await validate_brief(self.anthropic, current_brief)
            logger.info(format_validation_summary(validation))

            if validation["decision"] == "READY":
                return current_brief
            if validation["decision"] == "REJECT":
                return None

        return None

    def _save_script_to_ideas(self, idea_record_id: str, script: str) -> bool:
        """Persist script text to the Idea Concepts table immediately.

        Returns True if script was saved successfully, False otherwise.
        LOUD FAILURE: Sends Slack notification if save fails.
        """
        print(f"[DEBUG] _save_script_to_ideas called: record_id={idea_record_id}, script_len={len(script) if script else 0}")
        if not script:
            print("[DEBUG] Script is empty, skipping write")
            return False
        if not idea_record_id:
            print("[DEBUG] idea_record_id is empty, skipping write")
            return False
        try:
            print(f"[DEBUG] Writing {len(script)} chars to Airtable 'Script' field...")
            result = self.airtable.update_idea_fields(
                idea_record_id, {"Script": script}
            )
            print(f"[DEBUG] Airtable write result: {result}")

            # VERIFY the write succeeded by checking if Script is in the returned fields
            # If the field doesn't exist in Airtable, update_idea_fields silently drops it
            if "Script" not in result:
                error_msg = (
                    "🚨 *CRITICAL: Script field NOT saved to Airtable!*\n"
                    "The 'Script' field may not exist in the Idea Concepts table.\n"
                    "Add a Long Text field named 'Script' to the Idea Concepts table."
                )
                print(f"[ERROR] {error_msg}")
                logger.error(error_msg)
                self._notify(error_msg)
                return False

            logger.info("Script saved to Idea Concepts table")
            return True
        except Exception as e:
            error_msg = f"🚨 *Script field write FAILED:* {e}"
            print(f"[DEBUG] Airtable write FAILED: {e}")
            logger.error(f"Could not save script to Ideas: {e}")
            self._notify(error_msg)
            return False

    def _save_script_to_drive(
        self,
        script: str,
        brief: dict,
        project_folder_id: str = None,
    ) -> Optional[str]:
        """Save script as a Google Doc in the project's Drive folder.

        Mirrors the legacy run_script_bot() behavior: creates a Doc titled
        with the video title, appends the full script text, returns the URL.

        Returns:
            Google Doc URL, or None if Drive is unavailable.
        """
        if not self.google or not script:
            return None

        video_title = select_video_title(brief)

        try:
            doc = self.google.create_document(video_title, project_folder_id)
            if doc.get("unavailable"):
                logger.warning("Google Docs unavailable — script saved to Airtable only")
                return None

            doc_id = doc["id"]
            self.google.append_to_document(doc_id, script)
            doc_url = self.google.get_document_url(doc_id)
            logger.info(f"Script saved to Google Doc: {doc_url}")
            return doc_url
        except Exception as e:
            logger.warning(f"Could not save script to Google Drive: {e}")
            self._notify(f"⚠️ Google Drive doc write failed: {e}")
            return None

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
        return "\n".join(lines)

    def _write_editorial_to_ideas(self, idea_record_id: str, summary: str):
        """Write editorial validation summary to the Idea Concepts table."""
        if not summary:
            return
        try:
            self.airtable.update_idea_fields(
                idea_record_id, {"Script Validation": summary}
            )
        except Exception as e:
            logger.warning(f"Could not write Script Validation to Ideas: {e}")
            self._notify(f"⚠️ Script Validation field write failed: {e}")

    def _write_script_records(
        self,
        acts: dict,
        brief: dict,
        psych_assignments: list | None = None,
        unverified_claims: str = "",
        editorial_summary: str = "",
    ) -> list[str]:
        """Write script records to the Scripts table progressively (one per act)."""
        video_title = select_video_title(brief)
        sources_text = build_sources_list(brief)

        # Replace, don't append: a regenerated script (e.g. the retention auto-revise) must
        # clear the previous split's scene rows first, or the page shows doubled scenes and
        # reset voice progress. Scope the delete to THIS video by id (title is ambiguous).
        vid = getattr(self.airtable, "current_video_id", None)
        if vid and hasattr(self.airtable, "delete_scripts_for_video_id"):
            try:
                removed = self.airtable.delete_scripts_for_video_id(vid)
                if removed:
                    logger.info(f"Cleared {removed} prior script record(s) before rewrite")
            except Exception as e:
                logger.warning(f"Could not clear old script records before rewrite: {e}")

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
    google_client=None,
    project_folder_id: str = None,
    script_model: str = Models.CLAUDE_SONNET,
    video_config=None,
    script_system_prompt_override: Optional[str] = None,
    # Legacy params kept for backward compat — ignored
    total_images: int = 25,
    scene_output_dir: Optional[str] = None,
) -> dict:
    """Convenience function to run script generation.

    This is the main entry point for external callers.
    """
    translator = BriefTranslator(
        anthropic_client=anthropic_client,
        airtable_client=airtable_client,
        slack_client=slack_client,
        google_client=google_client,
        script_model=script_model,
        video_config=video_config,
        script_system_prompt_override=script_system_prompt_override,
    )
    return await translator.translate(
        idea_record_id, brief,
        project_folder_id=project_folder_id,
    )
