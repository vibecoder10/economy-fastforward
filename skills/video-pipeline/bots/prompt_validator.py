"""
Post-generation validation for image prompts.

Runs AFTER all prompts are written to Airtable, BEFORE status advances to "Ready For Images".
Checks sequencing rules, auto-fixes simple violations, and regenerates prompts that need it.

Violations checked:
- Camera distance clustering (3+ consecutive same shot type)
- Consecutive same location (3+ in same location)
- Consecutive data/chart scenes (3+ data visualizations)

Fix strategies:
- Camera distance: swap shot type (no regeneration needed)
- Location/data clustering: regenerate prompt via Claude with constraint
"""

from dataclasses import dataclass
from typing import Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Violation:
    """A validation violation found in the prompts."""

    type: str  # camera_distance, consecutive_location, consecutive_data
    image_index: int
    record_id: str
    issue: str
    fix: str  # swap_camera_distance, needs_regeneration
    severity: str  # low, medium, high


class PromptValidator:
    """Validate and fix sequencing issues in generated image prompts."""

    MAX_CONSECUTIVE_SAME_DISTANCE = 2
    MAX_CONSECUTIVE_SAME_LOCATION = 2
    MAX_CONSECUTIVE_DATA_SCENES = 2

    # Location markers for detection
    LOCATION_MARKERS = {
        "data_room": ["operations room", "projected display", "holographic", "control room monitors"],
        "kremlin": ["kremlin", "mahogany desk", "red square"],
        "treaty_room": ["treaty", "signing", "crossed flags", "ceremonial hall"],
        "eu_press": ["eu flag", "european union", "press conference"],
        "gas_station": ["gas station", "fuel pump", "gallon"],
        "kitchen": ["kitchen", "bills", "receipts", "coffee mug", "breakfast table"],
        "trading_floor": ["trading floor", "dow", "traders", "stock exchange"],
        "hormuz": ["strait", "hormuz", "tanker"],
        "afghanistan": ["afghanistan", "soviet", "command post"],
        "opec_1973": ["1973", "opec", "embargo", "arab ministers"],
        "boardroom": ["boardroom", "conference table", "executive"],
        "white_house": ["white house", "oval", "presidential"],
        "shipyard": ["shipyard", "container", "cargo"],
        "factory": ["factory floor", "assembly line", "industrial"],
        "refinery": ["refinery", "oil rig", "pipeline"],
    }

    # Data scene indicators
    DATA_INDICATORS = [
        "operations room",
        "projected display",
        "holographic",
        "bar chart",
        "line graph",
        "data visualization",
        "glowing digits",
        "percentage numbers",
        "financial dashboard",
        "stock ticker",
        "floating numbers",
        "data overlay",
        "pie chart",
        "trend line",
    ]

    def validate(self, prompts: list[dict]) -> list[Violation]:
        """Run all validation checks.

        Args:
            prompts: List of image records from Airtable, each with:
                - id: Record ID
                - Image Index: 1-based index
                - Image Prompt: The styled prompt text
                - Shot Type: Camera composition (wide/medium/closeup)
                - Scene: Scene number

        Returns:
            List of Violation objects
        """
        violations = []
        violations.extend(self._check_camera_distance(prompts))
        violations.extend(self._check_consecutive_locations(prompts))
        violations.extend(self._check_consecutive_data_scenes(prompts))
        return violations

    def _check_camera_distance(self, prompts: list[dict]) -> list[Violation]:
        """Flag runs of 3+ same camera distance."""
        violations = []
        consecutive = 1
        run_start_idx = 0

        for i in range(1, len(prompts)):
            current_type = prompts[i].get("Shot Type", "").lower()
            prev_type = prompts[i - 1].get("Shot Type", "").lower()

            if current_type == prev_type and current_type:
                consecutive += 1
                if consecutive > self.MAX_CONSECUTIVE_SAME_DISTANCE:
                    violations.append(
                        Violation(
                            type="camera_distance",
                            image_index=prompts[i].get("Image Index", i + 1),
                            record_id=prompts[i].get("id", ""),
                            issue=f"{consecutive}+ consecutive '{current_type}' shots (images {prompts[run_start_idx].get('Image Index', run_start_idx+1)}-{prompts[i].get('Image Index', i+1)})",
                            fix="swap_camera_distance",
                            severity="medium",
                        )
                    )
            else:
                consecutive = 1
                run_start_idx = i

        return violations

    def _check_consecutive_locations(self, prompts: list[dict]) -> list[Violation]:
        """Flag runs of 3+ same location."""
        violations = []
        consecutive = 1
        run_start_idx = 0

        for i in range(1, len(prompts)):
            prompt_text = prompts[i].get("Image Prompt", "")
            prev_prompt_text = prompts[i - 1].get("Image Prompt", "")

            loc_current = self._detect_location(prompt_text)
            loc_prev = self._detect_location(prev_prompt_text)

            if loc_current == loc_prev and loc_current != "unknown":
                consecutive += 1
                if consecutive > self.MAX_CONSECUTIVE_SAME_LOCATION:
                    violations.append(
                        Violation(
                            type="consecutive_location",
                            image_index=prompts[i].get("Image Index", i + 1),
                            record_id=prompts[i].get("id", ""),
                            issue=f"{consecutive}+ consecutive scenes in '{loc_current}' (images {prompts[run_start_idx].get('Image Index', run_start_idx+1)}-{prompts[i].get('Image Index', i+1)})",
                            fix="needs_regeneration",
                            severity="high",
                        )
                    )
            else:
                consecutive = 1
                run_start_idx = i

        return violations

    def _check_consecutive_data_scenes(self, prompts: list[dict]) -> list[Violation]:
        """Flag runs of 3+ data/chart scenes."""
        violations = []
        consecutive = 1
        run_start_idx = 0

        for i in range(1, len(prompts)):
            prompt_text = prompts[i].get("Image Prompt", "").lower()
            prev_prompt_text = prompts[i - 1].get("Image Prompt", "").lower()

            is_data_current = any(ind in prompt_text for ind in self.DATA_INDICATORS)
            is_data_prev = any(ind in prev_prompt_text for ind in self.DATA_INDICATORS)

            if is_data_current and is_data_prev:
                consecutive += 1
                if consecutive > self.MAX_CONSECUTIVE_DATA_SCENES:
                    violations.append(
                        Violation(
                            type="consecutive_data",
                            image_index=prompts[i].get("Image Index", i + 1),
                            record_id=prompts[i].get("id", ""),
                            issue=f"{consecutive}+ consecutive data/chart scenes (images {prompts[run_start_idx].get('Image Index', run_start_idx+1)}-{prompts[i].get('Image Index', i+1)})",
                            fix="needs_regeneration",
                            severity="high",
                        )
                    )
            else:
                consecutive = 1
                run_start_idx = i

        return violations

    def _detect_location(self, prompt_text: str) -> str:
        """Detect location from prompt text."""
        prompt_lower = prompt_text.lower()
        for loc_id, markers in self.LOCATION_MARKERS.items():
            if any(m in prompt_lower for m in markers):
                return loc_id
        return "unknown"

    # =========================================================================
    # AUTO-FIX METHODS
    # =========================================================================

    def auto_fix_camera_distance(
        self, prompts: list[dict], violation: Violation
    ) -> Optional[dict]:
        """Swap camera distance on the violating prompt.

        Returns:
            Dict with {record_id, new_shot_type} if fixed, None if not fixable
        """
        # Find the prompt by image index
        target_idx = None
        for i, p in enumerate(prompts):
            if p.get("Image Index") == violation.image_index:
                target_idx = i
                break

        if target_idx is None:
            return None

        current = prompts[target_idx].get("Shot Type", "medium").lower()

        # Pick a different distance that contrasts with neighbors
        alternatives = {
            "closeup": ["wide", "medium"],
            "close-up": ["wide", "medium"],
            "medium": ["closeup", "wide"],
            "wide": ["medium", "closeup"],
            "environmental": ["closeup", "medium"],
            "portrait": ["wide", "environmental"],
            "overhead": ["medium", "closeup"],
            "low_angle": ["medium", "wide"],
        }

        prev_type = prompts[target_idx - 1].get("Shot Type", "").lower() if target_idx > 0 else None
        next_type = (
            prompts[target_idx + 1].get("Shot Type", "").lower()
            if target_idx < len(prompts) - 1
            else None
        )

        for alt in alternatives.get(current, ["medium"]):
            if alt != prev_type and alt != next_type:
                return {
                    "record_id": prompts[target_idx].get("id"),
                    "new_shot_type": alt,
                    "old_shot_type": current,
                    "image_index": violation.image_index,
                }

        return None

    # =========================================================================
    # REGENERATION METHODS (Claude-powered prompt rewrite)
    # =========================================================================

    def build_regeneration_constraint(
        self, violation: Violation, prompts: list[dict]
    ) -> str:
        """Build a specific constraint string for the regeneration prompt.

        Args:
            violation: The violation to fix
            prompts: All prompts for context (neighbor detection)

        Returns:
            A constraint string describing what the new prompt must avoid/include
        """
        if violation.type == "consecutive_location":
            # Get surrounding prompts' locations (i-2, i-1, i+1, i+2) to avoid them ALL
            neighboring_locations = self._get_neighboring_locations(
                prompts, violation.image_index
            )
            if neighboring_locations:
                location_list = ", ".join(f"'{loc}'" for loc in neighboring_locations)
                return (
                    f"DO NOT use any of these locations: {location_list}. "
                    f"The surrounding images already use these locations. "
                    f"Choose a COMPLETELY DIFFERENT, visually distinct setting that fits the narration."
                )
            return "MUST use a different location than the previous images."

        elif violation.type == "consecutive_data":
            # Get surrounding prompts to describe what data types to avoid
            neighboring_data_types = self._get_neighboring_data_types(
                prompts, violation.image_index
            )
            if neighboring_data_types:
                type_list = ", ".join(neighboring_data_types)
                return (
                    f"MUST NOT be a data visualization, chart, graph, or operations room scene. "
                    f"The surrounding images already show: {type_list}. "
                    f"Show a physical environment, character action, or concrete object instead. "
                    f"NO holographic displays, NO floating data, NO dashboards."
                )
            return (
                "MUST NOT be a data visualization, chart, graph, or operations room scene. "
                "The previous images are already data scenes. "
                "Show a physical environment, character, or concrete object instead."
            )

        return f"Fix the following issue: {violation.issue}"

    def _get_neighboring_locations(
        self, prompts: list[dict], target_index: int
    ) -> list[str]:
        """Get locations from surrounding prompts (i-2, i-1, i+1, i+2).

        Returns a deduplicated list of location names that the target should avoid.
        """
        # Build index map for quick lookup
        index_to_prompt = {p.get("Image Index"): p for p in prompts}

        neighboring_indices = [
            target_index - 2,
            target_index - 1,
            target_index + 1,
            target_index + 2,
        ]

        locations = set()
        for idx in neighboring_indices:
            if idx in index_to_prompt:
                prompt_text = index_to_prompt[idx].get("Image Prompt", "")
                loc = self._detect_location(prompt_text)
                if loc != "unknown":
                    locations.add(loc)

        return list(locations)

    def _get_neighboring_data_types(
        self, prompts: list[dict], target_index: int
    ) -> list[str]:
        """Get data visualization types from surrounding prompts.

        Returns a list of detected data scene types (e.g., "bar chart", "operations room").
        """
        index_to_prompt = {p.get("Image Index"): p for p in prompts}

        neighboring_indices = [
            target_index - 2,
            target_index - 1,
            target_index + 1,
            target_index + 2,
        ]

        data_types = set()
        for idx in neighboring_indices:
            if idx in index_to_prompt:
                prompt_text = index_to_prompt[idx].get("Image Prompt", "").lower()
                for indicator in self.DATA_INDICATORS:
                    if indicator in prompt_text:
                        data_types.add(indicator)

        return list(data_types)

    def _find_prompt_by_index(
        self, prompts: list[dict], image_index: int
    ) -> Optional[dict]:
        """Find a prompt record by its image index."""
        for p in prompts:
            if p.get("Image Index") == image_index:
                return p
        return None

    async def regenerate_prompt(
        self,
        anthropic_client,
        violation: Violation,
        prompts: list[dict],
        story_bible: Optional[dict] = None,
    ) -> Optional[dict]:
        """Regenerate a single prompt that has a violation.

        Calls Claude with the narration text + story bible + constraint to
        produce a new prompt that respects the validation rules.

        Args:
            anthropic_client: AnthropicClient instance
            violation: The violation to fix
            prompts: All image prompts (for context/neighbors)
            story_bible: Story Bible dict from the idea record (characters, locations, etc.)

        Returns:
            Dict with {record_id, new_prompt, image_index} if regenerated, None if failed
        """
        target = self._find_prompt_by_index(prompts, violation.image_index)
        if not target:
            logger.warning(f"Could not find prompt for image index {violation.image_index}")
            return None

        narration = target.get("Sentence Text", "")
        old_prompt = target.get("Image Prompt", "")
        shot_type = target.get("Shot Type", "medium")
        scene_number = target.get("Scene", 0)
        constraint = self.build_regeneration_constraint(violation, prompts)

        # Build story bible context
        bible_context = ""
        if story_bible:
            characters = story_bible.get("characters", [])
            locations = story_bible.get("locations", [])
            if characters:
                bible_context += "\n\nSTORY BIBLE — CHARACTERS:\n"
                for char in characters:
                    if isinstance(char, dict):
                        bible_context += f"- {char.get('name', 'Unknown')}: {char.get('appearance', '')} wearing {char.get('clothing', 'business attire')}\n"
                    else:
                        bible_context += f"- {char}\n"
            if locations:
                bible_context += "\nSTORY BIBLE — LOCATIONS:\n"
                for loc in locations:
                    if isinstance(loc, dict):
                        bible_context += f"- {loc.get('name', 'Unknown')}: {loc.get('description', '')}\n"
                    else:
                        bible_context += f"- {loc}\n"

        # Style prefix/suffix detection removed - visual style is now dynamic
        # The regenerated prompt will be created fresh without requiring prefix preservation

        system_prompt = f"""You are a visual director rewriting an image prompt that violated a validation rule.

Your job: rewrite the SCENE DESCRIPTION portion of the prompt to fix the violation while keeping:
1. The same visual style as the original prompt
2. The same shot type ({shot_type})
3. Faithful representation of the narration text
4. Word count between 62-84 words total

CONSTRAINT: {constraint}
{bible_context}

OUTPUT FORMAT:
Return ONLY the complete image prompt text. No explanations, no JSON, no labels.
Preserve any style prefix/suffix from the original prompt."""

        user_prompt = f"""Rewrite this image prompt to fix the violation.

SCENE {scene_number}, IMAGE {violation.image_index}
NARRATION: "{narration}"
SHOT TYPE: {shot_type}

CURRENT PROMPT (violating):
"{old_prompt}"

VIOLATION: {violation.issue}

Write the fixed prompt:"""

        try:
            new_prompt = await anthropic_client.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=512,
                temperature=0.7,
            )

            # Clean up response (strip quotes, whitespace)
            new_prompt = new_prompt.strip().strip('"').strip("'").strip()

            if not new_prompt or len(new_prompt) < 20:
                logger.warning(f"Regeneration returned empty/short prompt for image {violation.image_index}")
                return None

            return {
                "record_id": target.get("id"),
                "new_prompt": new_prompt,
                "image_index": violation.image_index,
                "old_prompt": old_prompt,
                "violation_type": violation.type,
            }

        except Exception as e:
            logger.error(f"Failed to regenerate prompt for image {violation.image_index}: {e}")
            return None


def format_validation_report(
    video_title: str,
    total_prompts: int,
    violations: list[Violation],
    auto_fixed: list[dict],
    regenerated: list[dict] = None,
    still_failing: list[Violation] = None,
) -> str:
    """Format a Slack-ready validation report.

    Args:
        video_title: The video title
        total_prompts: Total number of prompts validated
        violations: All violations found in initial pass
        auto_fixed: List of auto-fix result dicts (camera swap, hand reinforcement)
        regenerated: List of regeneration result dicts (Claude-rewritten prompts)
        still_failing: Violations that still fail after regeneration + re-validation
    """
    regenerated = regenerated or []
    still_failing = still_failing or []

    lines = [
        f"*Prompt Validation Report*",
        f"Video: {video_title}",
        f"Total prompts: {total_prompts}",
        "",
    ]

    if auto_fixed:
        lines.append(f"*Auto-fixed: {len(auto_fixed)}*")
        for fix in auto_fixed:
            if "new_shot_type" in fix:
                lines.append(
                    f"  \u2022 Image {fix['image_index']}: camera distance {fix['old_shot_type']} \u2192 {fix['new_shot_type']}"
                )
        lines.append("")

    if regenerated:
        lines.append(f"*Regenerated via Claude: {len(regenerated)}*")
        for fix in regenerated:
            vtype = fix.get("violation_type", "unknown")
            lines.append(
                f"  \u2022 Image {fix['image_index']}: {vtype} \u2192 regenerated"
            )
        lines.append("")

    if still_failing:
        lines.append(f"*Still failing after fix: {len(still_failing)}*")
        for v in still_failing:
            lines.append(f"  \u2022 Image {v.image_index}: {v.issue}")
        lines.append("")

    if not violations:
        lines.append("*All prompts passed validation*")

    # Summary line with emoji
    if still_failing:
        lines.insert(0, f"\u26a0\ufe0f *{len(still_failing)} violations remain after auto-fix*\n")
    elif regenerated or auto_fixed:
        total_fixed = len(auto_fixed) + len(regenerated)
        lines.insert(0, f"\u2705 *Validation passed ({total_fixed} fixed)*\n")
    elif violations:
        lines.insert(0, "\u2705 *Validation passed - no issues found*\n")
    else:
        lines.insert(0, "\u2705 *Validation passed - no issues found*\n")

    return "\n".join(lines)
