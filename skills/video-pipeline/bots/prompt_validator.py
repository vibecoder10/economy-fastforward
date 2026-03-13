"""
Post-generation validation for image prompts.

Runs AFTER all prompts are written to Airtable, BEFORE status advances to "Ready For Images".
Checks sequencing rules and auto-fixes simple violations.

Violations checked:
- Camera distance clustering (3+ consecutive same shot type)
- Consecutive same location (3+ in same location)
- Consecutive data/chart scenes (3+ data visualizations)
- Mannequin hands without reinforcement (closeups with hands but no mannequin qualifier)
- Naked mannequins (character scenes without clothing descriptions)
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

    type: str  # camera_distance, consecutive_location, consecutive_data, realistic_hands, naked_mannequin
    image_index: int
    record_id: str
    issue: str
    fix: str  # swap_camera_distance, add_mannequin_hand_description, needs_regeneration
    severity: str  # low, medium, high, critical


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

    # Hand words that need mannequin reinforcement
    HAND_WORDS = [
        "hand resting",
        "hands resting",
        "hand reaching",
        "hands reaching",
        "hand gripping",
        "hands gripping",
        "fingers",
        "holding pen",
        "holding document",
        "hand on",
        "hands on",
    ]

    # Mannequin hand descriptors
    MANNEQUIN_HAND_WORDS = [
        "plastic",
        "white mannequin hand",
        "joint seam",
        "smooth white hand",
        "mannequin hand",
        "articulated joint",
        "plastic hand",
    ]

    # Character indicators (phrases that indicate a human figure is present, excluding "mannequin"
    # which is always in the prefix). Use multi-word phrases to avoid false positives like
    # "official seals" being detected as "official" (person).
    CHARACTER_INDICATORS = [
        "standing",
        "sitting",
        "leaning",
        "seated",
        "walking",
        "gesturing",
        "arms crossed",
        "hands clasped",
        "suited mannequin",
        "official seated",
        "official standing",
        "official at",
        "leader at",
        "leader seated",
        "trader at",
        "trader standing",
    ]

    # Standard mannequin prefix to strip before checking for character content
    MANNEQUIN_PREFIX = "3D rendered faceless mannequin with smooth white oval head"

    # Standard mannequin suffix that should be stripped before checking
    MANNEQUIN_SUFFIX = ", Cinematic 3D documentary style, no facial features on any figures."

    # Clothing descriptors
    CLOTHING_INDICATORS = [
        "wearing",
        "suit",
        "uniform",
        "robes",
        "dress shirt",
        "tie",
        "jacket",
        "vest",
        "shirt",
        "three-piece",
        "costume",
        "clerical",
        "thobe",
        "business attire",
        "formal wear",
        "coat",
        "blazer",
        "overalls",
        "coveralls",
        "military uniform",
        "lab coat",
        "hard hat",
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
        violations.extend(self._check_mannequin_hands(prompts))
        violations.extend(self._check_naked_mannequins(prompts))
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

    def _check_mannequin_hands(self, prompts: list[dict]) -> list[Violation]:
        """Flag closeup shots that describe hands without mannequin reinforcement."""
        violations = []

        for p in prompts:
            prompt_text = p.get("Image Prompt", "").lower()
            shot_type = p.get("Shot Type", "").lower()

            has_hands = any(hw in prompt_text for hw in self.HAND_WORDS)
            has_mannequin_hands = any(mhw in prompt_text for mhw in self.MANNEQUIN_HAND_WORDS)
            is_closeup = shot_type in ["closeup", "close-up", "extreme-close-up"]

            if has_hands and is_closeup and not has_mannequin_hands:
                violations.append(
                    Violation(
                        type="realistic_hands",
                        image_index=p.get("Image Index", 0),
                        record_id=p.get("id", ""),
                        issue="Closeup with hand description but no mannequin hand reinforcement",
                        fix="add_mannequin_hand_description",
                        severity="medium",
                    )
                )

        return violations

    def _check_naked_mannequins(self, prompts: list[dict]) -> list[Violation]:
        """Flag character prompts without clothing descriptions."""
        violations = []

        for p in prompts:
            prompt_text = p.get("Image Prompt", "")

            # Only check prompts that have the mannequin prefix (character scenes)
            if not prompt_text.startswith("3D rendered faceless mannequin"):
                continue

            # Strip the standard prefix and suffix before checking for character content
            # This prevents false positives from words like "mannequin" in the prefix
            # and "figures" in the standard suffix
            content = prompt_text
            if content.startswith(self.MANNEQUIN_PREFIX):
                content = content[len(self.MANNEQUIN_PREFIX):].strip()
            if content.endswith(self.MANNEQUIN_SUFFIX):
                content = content[:-len(self.MANNEQUIN_SUFFIX)].strip()

            content_lower = content.lower()

            # Check if this is a data/environment scene (not a character scene)
            is_data_scene = any(ind in content_lower for ind in self.DATA_INDICATORS)

            # Check for character presence and clothing
            has_character = any(ci in content_lower for ci in self.CHARACTER_INDICATORS)
            has_clothing = any(cl in content_lower for cl in self.CLOTHING_INDICATORS)

            # Only flag if it's a character scene without clothing
            # Skip data/environment scenes that incorrectly have the mannequin prefix
            if has_character and not has_clothing and not is_data_scene:
                violations.append(
                    Violation(
                        type="naked_mannequin",
                        image_index=p.get("Image Index", 0),
                        record_id=p.get("id", ""),
                        issue="Character scene with no clothing description",
                        fix="needs_regeneration",
                        severity="critical",
                    )
                )

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

    def auto_fix_mannequin_hands(
        self, prompts: list[dict], violation: Violation
    ) -> Optional[dict]:
        """Insert mannequin hand description into prompt.

        Returns:
            Dict with {record_id, new_prompt} if fixed, None if not fixable
        """
        # Find the prompt by image index
        target = None
        for p in prompts:
            if p.get("Image Index") == violation.image_index:
                target = p
                break

        if target is None:
            return None

        prompt = target.get("Image Prompt", "")
        original_prompt = prompt

        # Find hand description and add mannequin qualifier
        hand_replacements = {
            "hand resting": "smooth white plastic mannequin hand resting",
            "hands resting": "smooth white plastic mannequin hands resting",
            "hand reaching": "smooth white plastic mannequin hand reaching",
            "hands reaching": "smooth white plastic mannequin hands reaching",
            "hand gripping": "smooth white plastic mannequin hand gripping",
            "hands gripping": "smooth white plastic mannequin hands gripping",
            "hand on": "smooth white plastic mannequin hand on",
            "hands on": "smooth white plastic mannequin hands on",
            "holding pen": "plastic mannequin fingers holding pen",
            "holding document": "plastic mannequin hand holding document",
        }

        for original, replacement in hand_replacements.items():
            if original in prompt.lower():
                # Case-insensitive replacement
                import re
                prompt = re.sub(
                    re.escape(original),
                    replacement,
                    prompt,
                    flags=re.IGNORECASE,
                )
                break

        if prompt != original_prompt:
            return {
                "record_id": target.get("id"),
                "new_prompt": prompt,
                "image_index": violation.image_index,
            }

        return None


def format_validation_report(
    video_title: str,
    total_prompts: int,
    violations: list[Violation],
    auto_fixed: list[dict],
    needs_regen: list[Violation],
) -> str:
    """Format a Slack-ready validation report."""
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
            elif "new_prompt" in fix:
                lines.append(
                    f"  \u2022 Image {fix['image_index']}: added mannequin hand reinforcement"
                )
        lines.append("")

    if needs_regen:
        lines.append(f"*Needs regeneration: {len(needs_regen)}*")
        for v in needs_regen:
            lines.append(f"  \u2022 Image {v.image_index}: {v.issue}")
        lines.append("")

    if not violations:
        lines.append("*All prompts passed validation*")

    # Summary line with emoji
    critical = [v for v in needs_regen if v.severity == "critical"]
    if critical:
        lines.insert(0, f"\u26a0\ufe0f *{len(critical)} critical violations need manual review*\n")
    elif needs_regen:
        lines.insert(0, f"\u26a0\ufe0f *{len(needs_regen)} prompts flagged for review*\n")
    elif auto_fixed:
        lines.insert(0, f"\u2705 *Validation passed ({len(auto_fixed)} auto-fixed)*\n")
    else:
        lines.insert(0, "\u2705 *Validation passed - no issues found*\n")

    return "\n".join(lines)
