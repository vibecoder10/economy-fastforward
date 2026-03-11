"""Post-Generation Script Validation (Editorial Voice v2).

Validates generated scripts against editorial voice requirements AFTER
generation but BEFORE Airtable write. Catches LLM drift into framework
lectures, missing numbers, absent personal stakes, and weak closes.

Each check returns a ValidationResult. Failed checks produce targeted
retry prompts that fix the specific issue without full regeneration.

When a ScriptProfile is available, thresholds are read from the profile's
``validation``, ``number_density``, and ``framework_integration`` sections
via ``ScriptValidationConfig.from_profile()``.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from script_profiles.schema import ScriptProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ScriptValidationConfig:
    """Thresholds for post-generation script validation.

    Defaults match Power Doctrine v2 voice. Use ``from_profile()`` to
    populate from a loaded ScriptProfile at runtime.
    """

    # Check 1: Number density
    number_density_check: bool = True
    number_density_min: int = 19

    # Check 2: Framework density (max % of sentences with framework refs)
    framework_density_check: bool = True
    framework_max_pct: float = 0.15

    # Check 3: Personal stakes presence
    personal_stakes_check: bool = True
    personal_stakes_min_score: int = 3

    # Check 4: Actionable close
    actionable_close_check: bool = True
    actionable_close_min_score: int = 2

    # Check 5: Cliffhanger presence
    cliffhanger_check: bool = True

    # Retry settings — disabled. Validation is advisory (report-only).
    # Generate once → validate → report → move on.
    retry_on_fail: bool = False
    max_retries: int = 0

    @classmethod
    def from_profile(cls, profile: "ScriptProfile") -> "ScriptValidationConfig":
        """Build config from a ScriptProfile, pulling thresholds from
        ``profile.validation``, ``profile.number_density``, and
        ``profile.framework_integration``.
        """
        v = profile.validation
        return cls(
            number_density_check=v.number_density_check,
            number_density_min=profile.number_density.minimum_total,
            framework_density_check=v.framework_max_pct_check,
            framework_max_pct=profile.framework_integration.max_runtime_pct,
            personal_stakes_check=v.personal_stakes_presence,
            personal_stakes_min_score=3,  # no profile field yet — keep default
            actionable_close_check=v.actionable_ending_check,
            actionable_close_min_score=2,  # no profile field yet — keep default
            cliffhanger_check=v.cliffhanger_check,
            retry_on_fail=v.retry_on_fail,
            max_retries=v.max_retries,
        )


# Default config instance
DEFAULT_CONFIG = ScriptValidationConfig()


# ---------------------------------------------------------------------------
# Regex patterns for number detection
# ---------------------------------------------------------------------------

# Dollar amounts: $12, $3.5 billion, $847M
_DOLLAR_RE = re.compile(
    r"\$[\d,]+(?:\.[\d]+)?"
    r"(?:\s*(?:billion|million|trillion|B|M|T|bn|mn|trn))?"
)

# Percentages: 54%, 3.5%, 0.7%
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?%")

# Specific dates: January 14, 2024 / March 2026 / 14 January 2024
_DATE_MONTH_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2}(?:,?\s+\d{4})?"
)
_DATE_DMY_RE = re.compile(
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{4}"
)

# Years alone: 1973, 2024 (but not scene/act numbers like "Act 1")
_YEAR_RE = re.compile(r"(?<!\bAct\s)(?<!\bScene\s)(?<!\bPart\s)\b(1[6-9]\d{2}|20[0-3]\d)\b")

# Counts with units: 120 missiles, 7 million barrels, 14 targets
_COUNT_UNIT_RE = re.compile(
    r"\b\d[\d,]*\s+(?:soldiers|troops|missiles|ships|barrels|targets|"
    r"countries|companies|agreements|facilities|bases|drones|"
    r"workers|jobs|people|civilians|units|days|weeks|months|years|"
    r"hours|minutes|cents|dollars|euros|pounds|tons|miles|"
    r"kilometers|acres|weapons|bombs|aircraft|tanks|"
    r"members|nations|states|cities|regions|deals|contracts|"
    r"votes|seats|points|funds|firms|banks|investors)\b",
    re.IGNORECASE,
)

# Plain large numbers: 847, 12000, 3.5 (at least 2 digits, not scene/act nums)
_LARGE_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")

# Act/scene marker pattern to exclude from counting
_ACT_MARKER_RE = re.compile(r"\[ACT\s+\d+.*?\]", re.IGNORECASE)


def _count_specific_numbers(text: str) -> tuple[int, list[str]]:
    """Count specific, verifiable numbers in the script.

    Returns (count, list_of_found_numbers) for debugging.
    """
    # Strip act markers so we don't count "ACT 1", "350 words" etc.
    cleaned = _ACT_MARKER_RE.sub("", text)

    found: set[str] = set()

    for match in _DOLLAR_RE.finditer(cleaned):
        found.add(match.group())
    for match in _PERCENT_RE.finditer(cleaned):
        found.add(match.group())
    for match in _DATE_MONTH_RE.finditer(cleaned):
        found.add(match.group())
    for match in _DATE_DMY_RE.finditer(cleaned):
        found.add(match.group())
    for match in _YEAR_RE.finditer(cleaned):
        found.add(match.group())
    for match in _COUNT_UNIT_RE.finditer(cleaned):
        found.add(match.group().strip())

    return len(found), sorted(found)


def _extract_numbers_from_research(brief: dict) -> list[str]:
    """Extract all specific numbers from the research payload.

    Used to suggest unused numbers in retry prompts.
    Covers dollars, percentages, counts with units, years, and dates.
    """
    research_fields = [
        "fact_sheet", "historical_parallels", "character_dossier",
        "narrative_arc", "counter_arguments", "thesis",
    ]
    all_text = " ".join(str(brief.get(f, "")) for f in research_fields)

    numbers: set[str] = set()
    for match in _DOLLAR_RE.finditer(all_text):
        numbers.add(match.group())
    for match in _PERCENT_RE.finditer(all_text):
        numbers.add(match.group())
    for match in _COUNT_UNIT_RE.finditer(all_text):
        numbers.add(match.group().strip())
    for match in _YEAR_RE.finditer(all_text):
        numbers.add(match.group())
    for match in _DATE_MONTH_RE.finditer(all_text):
        numbers.add(match.group())
    for match in _DATE_DMY_RE.finditer(all_text):
        numbers.add(match.group())

    return sorted(numbers)


# ---------------------------------------------------------------------------
# Framework density detection
# ---------------------------------------------------------------------------

# Framework author names and key terminology
_FRAMEWORK_AUTHORS = [
    "machiavelli", "greene", "robert greene", "the prince",
    "thucydides", "thucydides trap",
    "taleb", "nassim taleb", "antifragile", "black swan",
    "sun tzu", "art of war",
    "brzezinski", "grand chessboard", "mackinder",
    "kindleberger", "kindleberger trap",
    "schelling", "focal point",
    "olson", "mancur olson", "collective action",
    "nye", "joseph nye", "soft power", "sharp power",
    "jung", "jungian", "shadow self",
    "kahneman", "tversky", "behavioral economics",
    "marcus aurelius", "seneca", "stoicism",
    "bernays", "chomsky", "propaganda model",
    "game theory", "nash equilibrium", "prisoner's dilemma",
    "systems thinking", "feedback loop",
]

# Compiled pattern: match any framework term (word boundaries)
_FRAMEWORK_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(a) for a in _FRAMEWORK_AUTHORS) + r")\b",
    re.IGNORECASE,
)

# Additional doctrine/military terminology that indicates framework explanation
_DOCTRINE_TERMS = re.compile(
    r"\b(?:OODA\s*loop|deterrence\s+theory|escalation\s+ladder|"
    r"containment\s+doctrine|balance\s+of\s+power|realpolitik|"
    r"hegemonic\s+stability|asymmetric\s+warfare\s+doctrine|"
    r"mutually\s+assured\s+destruction|first\s+strike\s+capability|"
    r"brinkmanship|credible\s+commitment|power\s+vacuum|"
    r"regulatory\s+capture|free\s+rider\s+problem)\b",
    re.IGNORECASE,
)


def _measure_framework_density(text: str) -> tuple[float, int, int]:
    """Measure what percentage of sentences contain framework references.

    Returns (percentage, framework_sentences, total_sentences).
    """
    # Split into sentences (rough but good enough)
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    total = len(sentences)
    if total == 0:
        return 0.0, 0, 0

    framework_count = 0
    for sentence in sentences:
        if _FRAMEWORK_PATTERN.search(sentence) or _DOCTRINE_TERMS.search(sentence):
            framework_count += 1

    pct = framework_count / total
    return pct, framework_count, total


# ---------------------------------------------------------------------------
# Personal stakes detection
# ---------------------------------------------------------------------------

_PERSONAL_STAKES_PATTERNS = [
    re.compile(r"\byour\s+(?:wallet|portfolio|401k|savings|retirement|job|"
               r"mortgage|rent|income|paycheck|career|family|future)\b", re.IGNORECASE),
    re.compile(r"\byou\s+(?:pay|lose|earn|save|spend|owe|risk|face)\b", re.IGNORECASE),
    re.compile(r"\b(?:gas\s+(?:prices?|hits?|reaches?)|grocery|rent\s+(?:increase|rise))\b",
               re.IGNORECASE),
    re.compile(r"\$[\d,]+(?:\.\d+)?.*?\b(?:per|a|each|every)\s+(?:year|month|week|day|gallon|barrel)\b",
               re.IGNORECASE),
    re.compile(r"\byour\s+\w+\s+(?:drops?|falls?|loses?|gains?|rises?)\s+\d", re.IGNORECASE),
    re.compile(r"\b(?:here'?s\s+what\s+(?:this|it)\s+means\s+for\s+you|"
               r"what\s+this\s+means\s+for\s+your)\b", re.IGNORECASE),
]


def _score_personal_stakes(text: str) -> tuple[int, list[str]]:
    """Score presence of personal financial stakes language.

    Returns (score, list_of_matches). Score = number of distinct patterns matched.
    """
    matches = []
    score = 0
    for pattern in _PERSONAL_STAKES_PATTERNS:
        found = pattern.findall(text)
        if found:
            score += 1
            matches.extend(found[:3])  # Cap per pattern
    return score, matches


# ---------------------------------------------------------------------------
# Actionable close detection
# ---------------------------------------------------------------------------

_ACTIONABLE_PATTERNS = [
    re.compile(r"\b(?:position\s+yourself|here'?s\s+the\s+play|the\s+play\s+is|"
               r"here'?s\s+what\s+you\s+(?:do|actually\s+do)|"
               r"so\s+what\s+do\s+you\s+actually\s+do)\b", re.IGNORECASE),
    re.compile(r"\b(?:watch\s+for|watch\s+the|the\s+signal\s+is|"
               r"look\s+for|monitor|track)\b", re.IGNORECASE),
    re.compile(r"\b(?:smart\s+money|repricing\s+window|the\s+trade|"
               r"buy|sell|hold|hedge|short|long\s+on|exposure)\b", re.IGNORECASE),
    re.compile(r"\b(?:when\s+you\s+see|when\s+(?:this|that)\s+happens?|"
               r"if\s+(?:this|that)\s+plays?\s+out)\b", re.IGNORECASE),
    re.compile(r"\b(?:the\s+(?:window|opportunity)\s+(?:opens?|closes?)|"
               r"\d+\s*(?:days?|weeks?|months?)\s+after)\b", re.IGNORECASE),
]


def _score_actionable_close(text: str) -> tuple[int, list[str]]:
    """Score the final section for actionable strategy language.

    Returns (score, list_of_matches).
    """
    matches = []
    score = 0
    for pattern in _ACTIONABLE_PATTERNS:
        found = pattern.findall(text)
        if found:
            score += 1
            matches.extend(found[:2])
    return score, matches


# ---------------------------------------------------------------------------
# Cliffhanger detection
# ---------------------------------------------------------------------------

_CLIFFHANGER_PATTERNS = re.compile(
    r"\b(?:what\s+you'?ll\s+see|what\s+(?:part|act|section)\s+\d|"
    r"(?:part|act|section)\s+\d\s+reveals?|"
    r"the\s+next\s+(?:section|part|act)|"
    r"don'?t\s+miss|that'?s\s+where|"
    r"coming\s+up|and\s+(?:that'?s|here'?s)\s+(?:where|what)|"
    r"(?:but|and)\s+there'?s\s+(?:one\s+more|another)\s+layer|"
    r"and\s+(?:that|this)\s+(?:is|brings\s+us\s+to)\s+(?:exactly|where)|"
    r"(?:but|and)\s+here'?s\s+what\s+none\s+of\s+this\s+explains|"
    r"the\s+part\s+that\s+affects\s+you)\b",
    re.IGNORECASE,
)


def _measure_per_act_framework(acts: dict[int, str]) -> dict[int, tuple[float, int, int]]:
    """Measure framework density per act.

    Returns dict mapping act_num -> (percentage, fw_sentences, total_sentences).
    """
    return {
        act_num: _measure_framework_density(act_text)
        for act_num, act_text in acts.items()
    }


def _extract_personal_stakes_figures(brief: dict) -> dict[str, list[str]]:
    """Extract specific figures relevant to personal financial impact from research.

    Returns dict with categories of figures: prices, percentages, job/wage figures.
    """
    fields = ["fact_sheet", "thesis", "counter_arguments", "narrative_arc"]
    all_text = " ".join(str(brief.get(f, "")) for f in fields)

    prices: list[str] = []
    percentages: list[str] = []
    counts: list[str] = []

    for match in _DOLLAR_RE.finditer(all_text):
        prices.append(match.group())
    for match in _PERCENT_RE.finditer(all_text):
        percentages.append(match.group())
    for match in _COUNT_UNIT_RE.finditer(all_text):
        counts.append(match.group().strip())

    return {
        "prices": sorted(set(prices)),
        "percentages": sorted(set(percentages)),
        "counts": sorted(set(counts)),
    }


def _count_cliffhangers_at_transitions(script: str, acts: dict[int, str]) -> tuple[int, int]:
    """Count cliffhangers at act transitions.

    Checks the final ~150 words of each act (except the last) for
    forward-selling language.

    Returns (cliffhangers_found, transitions_expected).
    """
    sorted_acts = sorted(acts.keys())
    transitions = len(sorted_acts) - 1
    if transitions <= 0:
        return 0, 0

    cliffhangers = 0
    for act_num in sorted_acts[:-1]:  # Skip last act
        act_text = acts[act_num]
        # Check final ~150 words
        words = act_text.split()
        tail = " ".join(words[-150:]) if len(words) > 150 else act_text

        if _CLIFFHANGER_PATTERNS.search(tail):
            cliffhangers += 1

    return cliffhangers, transitions


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Result of a single validation check."""
    name: str
    passed: bool
    detail: str
    retry_prompt: str = ""


@dataclass
class ScriptValidationResult:
    """Aggregated result of all post-generation validation checks."""
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    @property
    def summary(self) -> str:
        lines = []
        for c in self.checks:
            status = "PASS" if c.passed else "FAIL"
            lines.append(f"  [{status}] {c.name}: {c.detail}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


# ---------------------------------------------------------------------------
# Main validation function
# ---------------------------------------------------------------------------

def validate_script_editorial(
    script: str,
    brief: dict,
    acts: dict[int, str],
    config: Optional[ScriptValidationConfig] = None,
) -> ScriptValidationResult:
    """Run all 5 editorial voice validation checks on a generated script.

    Args:
        script: Full generated script text.
        brief: Research brief dict (for extracting unused numbers).
        acts: Dict mapping act number to act text (from extract_acts).
        config: Validation thresholds. Uses DEFAULT_CONFIG if None.

    Returns:
        ScriptValidationResult with per-check results and retry prompts.
    """
    if config is None:
        config = DEFAULT_CONFIG

    result = ScriptValidationResult()

    # --- Check 1: Number Density ---
    if config.number_density_check:
        count, found_numbers = _count_specific_numbers(script)
        passed = count >= config.number_density_min
        detail = f"{count}/{config.number_density_min} specific numbers found"

        retry_prompt = ""
        if not passed:
            # Find unused numbers from research
            research_numbers = _extract_numbers_from_research(brief)
            script_lower = script.lower()
            unused = [n for n in research_numbers if n.lower() not in script_lower]
            needed = config.number_density_min - count

            retry_prompt = (
                f"NUMBERS: Your script contains {count} specific numbers. "
                f"Minimum is {config.number_density_min}. "
                f"You need {needed} more.\n\n"
                f"ALREADY IN SCRIPT: {', '.join(found_numbers[:15])}\n\n"
                f"UNUSED NUMBERS FROM RESEARCH — you MUST integrate at least "
                f"{needed} of these:\n{', '.join(unused)}\n\n"
                f"INSTRUCTIONS:\n"
                f"- Replace every instance of 'significant', 'massive', "
                f"'substantial', 'major', 'considerable' with a specific "
                f"number from the list above.\n"
                f"- Every claim needs a number: not 'oil prices rose' but "
                f"'oil prices rose 300% to $X/barrel'.\n"
                f"- Distribute numbers across all 6 acts, not just Acts 1-2."
            )

        result.checks.append(CheckResult(
            name="number_density",
            passed=passed,
            detail=detail,
            retry_prompt=retry_prompt,
        ))

    # --- Check 2: Framework Density ---
    if config.framework_density_check:
        pct, fw_sentences, total_sentences = _measure_framework_density(script)
        passed = pct <= config.framework_max_pct
        detail = (
            f"{pct:.0%} framework density "
            f"({fw_sentences}/{total_sentences} sentences)"
        )

        retry_prompt = ""
        if not passed:
            # Identify which acts are framework-heavy
            per_act = _measure_per_act_framework(acts) if acts else {}
            heavy_acts = [
                (act_num, act_pct, act_fw, act_total)
                for act_num, (act_pct, act_fw, act_total) in sorted(per_act.items())
                if act_pct > config.framework_max_pct
            ]
            heavy_detail = "\n".join(
                f"  - Act {a}: {p:.0%} framework ({f}/{t} sentences)"
                for a, p, f, t in heavy_acts
            )

            retry_prompt = (
                f"FRAMEWORK OVERLOAD: {pct:.0%} of sentences reference "
                f"frameworks/doctrines ({fw_sentences}/{total_sentences}). "
                f"Maximum is {config.framework_max_pct:.0%}.\n\n"
                f"WORST OFFENDERS:\n{heavy_detail}\n\n"
                f"FIX INSTRUCTIONS:\n"
                f"- Acts 1-3 must contain ZERO framework names. Show the "
                f"pattern through events, money flows, and specific actions. "
                f"Instead of 'Thucydides Trap explains this', write 'The "
                f"last five times a rising power challenged trade routes, "
                f"the incumbent spent 3x on military within 18 months.'\n"
                f"- Act 4 can NAME the framework ONCE as a reveal.\n"
                f"- For each framework sentence you cut, add a specific "
                f"money trail, dollar figure, or personal impact sentence.\n"
                f"- DELETE sentences that explain what a framework IS. "
                f"The viewer doesn't need a political science lecture."
            )

        result.checks.append(CheckResult(
            name="framework_density",
            passed=passed,
            detail=detail,
            retry_prompt=retry_prompt,
        ))

    # --- Check 3: Personal Stakes Presence ---
    if config.personal_stakes_check:
        score, matches = _score_personal_stakes(script)
        passed = score >= config.personal_stakes_min_score
        detail = f"personal stakes score {score}/{config.personal_stakes_min_score}"
        if matches:
            detail += f" (found: {', '.join(matches[:3])})"

        retry_prompt = ""
        if not passed:
            # Extract actual figures from research for the template
            figures = _extract_personal_stakes_figures(brief)
            price_examples = ", ".join(figures["prices"][:5]) or "N/A"
            pct_examples = ", ".join(figures["percentages"][:5]) or "N/A"
            count_examples = ", ".join(figures["counts"][:5]) or "N/A"

            retry_prompt = (
                f"PERSONAL STAKES MISSING: Score {score}/{config.personal_stakes_min_score}. "
                f"The script talks ABOUT consequences but never addresses the "
                f"viewer directly with specific dollar impacts.\n\n"
                f"AVAILABLE FIGURES FROM RESEARCH:\n"
                f"  Prices: {price_examples}\n"
                f"  Percentages: {pct_examples}\n"
                f"  Quantities: {count_examples}\n\n"
                f"ADD THIS STRUCTURE TO ACT 5 (adapt with real figures above):\n"
                f"  1. 'Here's what this means for your wallet.'\n"
                f"  2. Gas/energy impact: '$X per gallon means $Y more per year "
                f"for the average American household.'\n"
                f"  3. Portfolio exposure: 'X% of the S&P 500 is [sector]. "
                f"Your 401k has more exposure to [risk] than you think.'\n"
                f"  4. Job/wage impact: 'If [scenario], your real wages decline "
                f"X% — that's $Y less purchasing power per month.'\n"
                f"  5. Direct address: 'You pay more at the pump, your "
                f"retirement fund drops, your grocery bill rises.'\n\n"
                f"REQUIRED PHRASES (use at least 3): 'your wallet', 'your 401k', "
                f"'you pay', 'your savings', 'your retirement', "
                f"'what this means for you'."
            )

        result.checks.append(CheckResult(
            name="personal_stakes",
            passed=passed,
            detail=detail,
            retry_prompt=retry_prompt,
        ))

    # --- Check 4: Actionable Close ---
    if config.actionable_close_check:
        # Check the final ~20% of the script (approximately Act 6)
        words = script.split()
        final_section = " ".join(words[int(len(words) * 0.80):])
        score, matches = _score_actionable_close(final_section)
        passed = score >= config.actionable_close_min_score
        detail = f"actionable close score {score}/{config.actionable_close_min_score}"
        if matches:
            detail += f" (found: {', '.join(matches[:3])})"

        retry_prompt = ""
        if not passed:
            # Pull historical data from research for the template
            hist_text = str(brief.get("historical_parallels", ""))
            counter_text = str(brief.get("counter_arguments", ""))

            retry_prompt = (
                f"WEAK CLOSE: Score {score}/{config.actionable_close_min_score}. "
                f"The final act reads like a conclusion, not a strategy briefing.\n\n"
                f"HISTORICAL DATA FROM RESEARCH (use for timing):\n"
                f"  {hist_text[:300]}\n\n"
                f"REWRITE THE FINAL ACT WITH THIS 3-PHASE STRUCTURE:\n"
                f"  Phase 1 — THE SHOCK: 'When [event] hits, do NOT [panic "
                f"sell/buy]. Smart money didn't move for X days after "
                f"[historical parallel].'\n"
                f"  Phase 2 — THE REPRICING WINDOW: 'X days after [shock], "
                f"the repricing window opens. Watch for [specific signal: "
                f"insurance premium, VIX level, yield curve]. That's when "
                f"smart money moved in [year].'\n"
                f"  Phase 3 — THE ROTATION: 'The sectors that benefit are "
                f"[specific names]. The play is [specific position]. Position "
                f"yourself before the repricing, not during it.'\n\n"
                f"REQUIRED PHRASES (use at least 2): 'position yourself', "
                f"'watch for', 'the play is', 'here's what you do', "
                f"'smart money', 'when you see'."
            )

        result.checks.append(CheckResult(
            name="actionable_close",
            passed=passed,
            detail=detail,
            retry_prompt=retry_prompt,
        ))

    # --- Check 5: Cliffhanger Presence ---
    if config.cliffhanger_check:
        found, expected = _count_cliffhangers_at_transitions(script, acts)
        passed = found >= expected if expected > 0 else True
        detail = f"{found}/{expected} act transitions have cliffhangers"

        retry_prompt = ""
        if not passed:
            missing = expected - found
            # Identify which specific act endings are missing cliffhangers
            # AND extract the opening of the next act for teaser material
            sorted_acts = sorted(acts.keys())
            missing_acts = []
            per_act_instructions = []
            for act_num in sorted_acts[:-1]:
                act_text = acts[act_num]
                words = act_text.split()
                tail = " ".join(words[-150:]) if len(words) > 150 else act_text
                if not _CLIFFHANGER_PATTERNS.search(tail):
                    missing_acts.append(act_num)
                    # Get the next act's opening content for teaser material
                    next_act_num = sorted_acts[sorted_acts.index(act_num) + 1]
                    next_act_text = acts.get(next_act_num, "")
                    next_act_opening = " ".join(next_act_text.split()[:80])
                    per_act_instructions.append(
                        f"  ACT {act_num} → ACT {next_act_num}:\n"
                        f"    Next act opens with: \"{next_act_opening}...\"\n"
                        f"    Add to end of Act {act_num}: 'And what you'll see "
                        f"in the next section is [specific teaser from the "
                        f"content above]. That's where [payoff preview].'"
                    )

            act_list = ", ".join(str(a) for a in missing_acts)
            act_details = "\n\n".join(per_act_instructions)

            retry_prompt = (
                f"MISSING CLIFFHANGERS: Your script has cliffhangers at "
                f"{found}/{expected} act transitions. Missing after "
                f"Acts {act_list}.\n\n"
                f"At the end of each missing act, add an explicit forward "
                f"sell using this template:\n"
                f"  'And what you'll see in the next section is [specific "
                f"teaser pulled from the next act's actual content]. "
                f"That's where [payoff preview].'\n\n"
                f"HERE IS WHAT EACH NEXT ACT CONTAINS — use this for "
                f"your teasers:\n\n"
                f"{act_details}\n\n"
                f"RULES:\n"
                f"  - Do NOT use generic language like 'things get "
                f"interesting' or 'stay tuned.'\n"
                f"  - Reference SPECIFIC content from the next act — "
                f"a number, a player, a revelation.\n"
                f"  - Do NOT add cliffhangers to the final act.\n"
                f"  - Do NOT increase the overall word count significantly. "
                f"Replace weak closing sentences rather than adding new ones."
            )

        result.checks.append(CheckResult(
            name="cliffhanger_presence",
            passed=passed,
            detail=detail,
            retry_prompt=retry_prompt,
        ))

    return result


def build_retry_prompt(
    original_prompt: str,
    script: str,
    validation: ScriptValidationResult,
) -> str:
    """Build a targeted retry prompt from failed validation checks.

    Sends the FULL original script back with specific fix instructions
    rather than regenerating from scratch.
    """
    fix_instructions = []
    for check in validation.failed_checks:
        if check.retry_prompt:
            fix_instructions.append(check.retry_prompt)

    combined_fixes = "\n\n".join(fix_instructions)

    return (
        f"{original_prompt}\n\n"
        f"=== REVISION REQUIRED ===\n\n"
        f"Your previous script (below) failed {len(validation.failed_checks)} "
        f"editorial validation check(s). Fix ONLY the issues listed below. "
        f"Keep the overall structure, narrative, and act boundaries intact. "
        f"Do NOT regenerate from scratch — revise the existing script.\n\n"
        f"ISSUES TO FIX:\n{combined_fixes}\n\n"
        f"PREVIOUS SCRIPT:\n{script}"
    )
