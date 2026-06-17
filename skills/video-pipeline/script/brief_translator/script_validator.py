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
    from shared.profiles.script.schema import ScriptProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ScriptValidationConfig:
    """Thresholds for post-generation script validation.

    The DEFAULTS here are IDENTITY-NEUTRAL — they only enable the universal
    craft checks that apply to any channel (cliffhangers, promise/payoff,
    act coherence). The identity-specific checks (number density, framework
    density, "personal stakes", actionable/investment close) are OFF by
    default so that a non-Power-Doctrine channel (ESL kids' stories, cooking,
    etc.) is never blocked for failing to sound like Power Doctrine.

    A loaded ``ScriptProfile`` can re-enable any of these via
    ``from_profile()`` — e.g. a "power_doctrine_v2" profile turns number
    density and framework density back on with PD thresholds. That is how the
    Power Doctrine identity is reintroduced: as one profile among many, not as
    the hard-wired default.
    """

    # Check 1: Number density — IDENTITY (PD "every claim gets a number").
    # Off by default; a story/cooking script should not be failed for lacking
    # statistics. Re-enabled by a profile that wants data-dense scripts.
    number_density_check: bool = False
    number_density_min: int = 19

    # Check 2: Framework density — IDENTITY (keyed off a hardcoded PD author
    # list: Machiavelli, Thucydides, Sun Tzu, …). Off by default; only
    # meaningful for an analytical/geopolitics identity. Re-enabled by profile.
    framework_density_check: bool = False
    framework_max_pct: float = 0.15

    # Check 3: Personal stakes presence — IDENTITY (PD "your wallet / your
    # 401k" personal-finance framing). Off by default. Re-enabled by profile.
    personal_stakes_check: bool = False
    personal_stakes_min_score: int = 1

    # Check 4: Actionable close — IDENTITY (PD "position yourself / smart
    # money" investment framing). Off by default. Re-enabled by profile.
    actionable_close_check: bool = False
    actionable_close_min_score: int = 2

    # Check 5: Cliffhanger presence — UNIVERSAL retention craft. On by default.
    cliffhanger_check: bool = True

    # Check 6: Promise-payoff tracking — UNIVERSAL structural craft. On.
    promise_payoff_check: bool = True

    # Check 7: Act coherence (topic drift) — UNIVERSAL pacing craft (advisory).
    # Threshold of 6 allows complex multi-subject narratives without false
    # positives.
    act_coherence_check: bool = True
    act_coherence_max_topics: int = 6

    # Retry settings — validation is now BLOCKING.
    # Scripts must pass all checks before advancing to voice.
    # Senior editor gets ONE pass to fix issues; if still failing,
    # pipeline blocks and requires manual approval.
    retry_on_fail: bool = True
    max_retries: int = 1  # One senior editor pass

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
            personal_stakes_min_score=1,  # one match is enough — cinematic stakes
            actionable_close_check=v.actionable_ending_check,
            actionable_close_min_score=2,  # no profile field yet — keep default
            cliffhanger_check=v.cliffhanger_check,
            # Universal craft checks — always enabled, use defaults
            promise_payoff_check=True,
            act_coherence_check=True,
            act_coherence_max_topics=6,  # lenient: allow multi-subject acts
            # Validation is now blocking
            retry_on_fail=True,
            max_retries=1,
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
    # Broad: any dollar amount signals personal/financial stakes in the scene
    re.compile(r"\$\d[\d,]*(?:\.\d+)?", re.IGNORECASE),
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
# Promise-Payoff Tracking (Check 6)
# ---------------------------------------------------------------------------

# Patterns that indicate a forward reference / promise
_PROMISE_PATTERNS = [
    # Explicit act/part references
    re.compile(
        r"(?:what\s+)?(?:part|act|section)\s+(\d+)\s+(?:reveals?|shows?|covers?|explains?|exposes?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:that'?s\s+(?:exactly\s+)?what|that'?s\s+where)\s+(?:part|act|section)\s+(\d+)",
        re.IGNORECASE,
    ),
    # Forward teases
    re.compile(
        r"(?:what\s+you'?ll\s+see|what\s+(?:comes|happens)\s+next|"
        r"(?:in\s+)?the\s+next\s+(?:section|part|act))",
        re.IGNORECASE,
    ),
    # Promises with specific content
    re.compile(
        r"(?:here'?s\s+what\s+(?:this|that|it)\s+means|"
        r"(?:and\s+)?(?:that|this)\s+is\s+(?:exactly\s+)?(?:where|what|how)|"
        r"(?:but\s+)?first,?\s+(?:we\s+need\s+to|let'?s|you\s+need\s+to))",
        re.IGNORECASE,
    ),
    # Specific payoff promises
    re.compile(
        r"(?:you'?ll\s+(?:see|learn|discover|understand)|"
        r"(?:we'?ll|I'?ll)\s+(?:show|reveal|explain|cover))",
        re.IGNORECASE,
    ),
]


def _extract_promises(script: str, acts: dict[int, str]) -> list[dict]:
    """Extract forward references/promises from the script.

    Returns list of dicts with:
        - act: int (act number where promise appears)
        - text: str (the promise text)
        - target_act: int or None (if a specific act is referenced)
        - promise_content: str (what was promised)
    """
    promises = []

    for act_num, act_text in acts.items():
        # Split into sentences for context
        sentences = re.split(r'[.!?]+', act_text)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue

            for pattern in _PROMISE_PATTERNS:
                match = pattern.search(sentence)
                if match:
                    # Try to extract target act number
                    target_act = None
                    groups = match.groups()
                    if groups and groups[0] and groups[0].isdigit():
                        target_act = int(groups[0])

                    # Extract what was promised (rest of sentence after match)
                    promise_content = sentence[match.end():].strip()
                    if not promise_content:
                        # Use the full sentence as context
                        promise_content = sentence

                    promises.append({
                        "act": act_num,
                        "text": sentence[:200],  # Truncate for readability
                        "target_act": target_act,
                        "promise_content": promise_content[:100],
                    })
                    break  # One match per sentence is enough

    return promises


def _verify_promise_payoff(
    promise: dict,
    acts: dict[int, str],
) -> tuple[bool, str]:
    """Verify a single promise is resolved in a later act.

    Returns (is_resolved, detail_message).
    """
    source_act = promise["act"]
    target_act = promise.get("target_act")
    promise_content = promise["promise_content"].lower()

    # Extract key nouns/concepts from the promise (simplified)
    # Remove common words to get meaningful content words
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "this", "that",
        "these", "those", "what", "where", "when", "why", "how", "which",
        "who", "whom", "it", "its", "you", "your", "we", "our", "they",
        "their", "and", "or", "but", "if", "then", "so", "for", "of", "to",
        "in", "on", "at", "by", "with", "from", "about", "into", "through",
    }

    content_words = [
        w for w in re.findall(r'\b\w{4,}\b', promise_content)
        if w.lower() not in stopwords
    ]

    if not content_words:
        # Can't verify, assume OK
        return True, "No verifiable content in promise"

    # Check target act specifically, or all subsequent acts
    acts_to_check = {}
    if target_act and target_act in acts and target_act > source_act:
        acts_to_check = {target_act: acts[target_act]}
    else:
        # Check all acts after the promise
        acts_to_check = {
            num: text for num, text in acts.items()
            if num > source_act
        }

    if not acts_to_check:
        # Promise at end of script with no later acts
        if target_act and target_act > max(acts.keys()):
            return False, f"References Act {target_act} which doesn't exist"
        return True, "Final act promise (no resolution expected)"

    # Check if content words appear in subsequent acts
    for act_num, act_text in acts_to_check.items():
        act_lower = act_text.lower()
        matches = sum(1 for w in content_words if w in act_lower)
        # Require at least 30% of content words to appear
        if matches >= max(1, len(content_words) * 0.3):
            return True, f"Resolved in Act {act_num}"

    # Not found
    if target_act:
        return False, f"Promised in Act {source_act} → Act {target_act} doesn't deliver"
    return False, f"Promised in Act {source_act} but no resolution found"


def _check_promise_payoff(
    script: str,
    acts: dict[int, str],
) -> tuple[bool, list[dict], str]:
    """Check all promises have payoffs.

    Returns (passed, broken_promises, detail_string).
    """
    promises = _extract_promises(script, acts)

    if not promises:
        return True, [], "No forward references detected"

    broken = []
    for promise in promises:
        resolved, detail = _verify_promise_payoff(promise, acts)
        if not resolved:
            broken.append({
                **promise,
                "resolution_detail": detail,
            })

    if not broken:
        return True, [], f"{len(promises)} promises verified"

    return False, broken, f"{len(broken)}/{len(promises)} promises unresolved"


# ---------------------------------------------------------------------------
# Act Coherence / Topic Drift Detection (Check 7)
# ---------------------------------------------------------------------------

# Geographic/political clusters — terms that belong to the same topic
# Each cluster maps a canonical name to all related terms
_GEOPOLITICAL_CLUSTERS: dict[str, set[str]] = {
    "iran": {"iran", "iranian", "tehran", "persia", "persian", "hormuz", "khamenei", "rouhani", "raisi", "irgc", "quds"},
    "russia": {"russia", "russian", "moscow", "kremlin", "putin", "lavrov", "medvedev", "soviet", "ussr"},
    "china": {"china", "chinese", "beijing", "xi", "jinping", "ccp", "prc", "taiwan", "taipei", "pla"},
    "usa": {"usa", "american", "america", "washington", "biden", "trump", "pentagon", "congress", "white house"},
    "saudi": {"saudi", "arabia", "riyadh", "mbs", "salman", "aramco", "opec"},
    "israel": {"israel", "israeli", "netanyahu", "tel aviv", "jerusalem", "idf", "mossad"},
    "ukraine": {"ukraine", "ukrainian", "kyiv", "kiev", "zelenskyy", "zelensky", "donbas", "crimea"},
    "europe": {"europe", "european", "eu", "brussels", "nato", "germany", "german", "france", "french", "uk", "british"},
    "gulf": {"gulf", "gcc", "uae", "emirates", "qatar", "bahrain", "kuwait", "oman"},
    "energy": {"oil", "gas", "opec", "barrel", "pipeline", "lng", "crude", "refinery", "energy"},
    "finance": {"fed", "federal reserve", "treasury", "imf", "world bank", "dollar", "yuan", "euro"},
}


def _normalize_to_cluster(term: str) -> str:
    """Normalize a term to its canonical cluster name, or return the term itself."""
    term_lower = term.lower()
    for cluster_name, members in _GEOPOLITICAL_CLUSTERS.items():
        if term_lower in members:
            return cluster_name
        # Partial match for multi-word terms
        for member in members:
            if member in term_lower or term_lower in member:
                return cluster_name
    return term_lower


def _extract_topics_from_act(act_text: str) -> list[str]:
    """Extract distinct topics/subjects from an act.

    Uses a simplified approach:
    - Split into paragraphs
    - Extract key noun phrases from each paragraph
    - Identify when a new subject is introduced vs continuing previous
    - Flag when proper nouns change significantly between paragraphs
    """
    # Split into paragraphs (double newline or significant whitespace)
    paragraphs = re.split(r'\n\s*\n|\n{2,}', act_text)
    paragraphs = [p.strip() for p in paragraphs if len(p.strip()) > 30]

    if len(paragraphs) <= 1:
        return []  # Single paragraph = single topic

    topics = []
    prev_clustered_pn: set[str] = set()
    prev_clustered_domain: set[str] = set()

    # Common sentence starters to exclude
    _STARTERS = {
        "the", "this", "that", "these", "those", "when", "what", "where",
        "why", "how", "but", "and", "or", "if", "so", "now", "here",
        "there", "in", "on", "at", "for", "with", "from", "to", "by",
        "meanwhile", "however", "analysts", "investors", "experts",
    }

    for i, para in enumerate(paragraphs):
        # Extract multi-word proper nouns (more reliable indicator)
        multi_word_pn = set(re.findall(
            r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', para
        ))

        # Extract single-word proper nouns (4+ chars to avoid noise)
        single_pn = set(re.findall(r'\b([A-Z][a-z]{3,})\b', para))
        single_pn = {n for n in single_pn if n.lower() not in _STARTERS}

        proper_nouns = multi_word_pn | single_pn

        # Normalize proper nouns to clusters (Iran, Iranian, Tehran → "iran")
        # This prevents treating related geopolitical terms as separate topics
        clustered_pn = {_normalize_to_cluster(pn) for pn in proper_nouns}

        # Extract domain-specific terms
        domain_terms = set(re.findall(
            r'\b(iphone|android|tesla|bitcoin|oil|opec|nato|'
            r'china|russia|ukraine|taiwan|iran|saudi|'
            r'tariff|sanction|alliance|treaty|invasion|'
            r'stock|revenue|profit|billion|trillion)\b',
            para.lower()
        ))

        # Normalize domain terms to clusters too
        clustered_domain = {_normalize_to_cluster(dt) for dt in domain_terms}

        # Check for topic shift using CLUSTERED terms (not raw)
        if i > 0 and (prev_clustered_pn or prev_clustered_domain):
            # Calculate overlap using normalized clusters
            pn_overlap = clustered_pn & prev_clustered_pn
            domain_overlap = clustered_domain & prev_clustered_domain

            new_pn_clusters = clustered_pn - prev_clustered_pn
            new_domain_clusters = clustered_domain - prev_clustered_domain

            # Topic shift if:
            # 1. No overlap in proper noun CLUSTERS AND new clusters introduced
            # 2. OR significant new domain CLUSTERS with no overlap
            has_pn_shift = (
                len(pn_overlap) == 0 and
                len(new_pn_clusters) >= 1 and
                len(clustered_pn) >= 1
            )
            has_domain_shift = (
                len(domain_overlap) == 0 and
                len(new_domain_clusters) >= 2 and
                len(prev_clustered_domain) >= 1
            )

            if has_pn_shift or has_domain_shift:
                # New topic detected — use cluster names for label
                label_parts = sorted(new_pn_clusters)[:2] + sorted(new_domain_clusters)[:2]
                topic_label = ", ".join(label_parts[:3])
                if topic_label:
                    topics.append(topic_label)

        prev_clustered_pn = clustered_pn
        prev_clustered_domain = clustered_domain

    return topics


def _check_act_coherence(
    acts: dict[int, str],
    max_topics_per_act: int = 3,
) -> tuple[bool, dict[int, list[str]], str]:
    """Check each act for topic coherence (no excessive drift).

    Returns (passed, drifting_acts, detail_string).
    drifting_acts maps act_num -> list of detected topic shifts
    """
    drifting_acts = {}

    for act_num, act_text in acts.items():
        topics = _extract_topics_from_act(act_text)
        if len(topics) >= max_topics_per_act:
            drifting_acts[act_num] = topics

    if not drifting_acts:
        return True, {}, "All acts maintain topic coherence"

    act_details = [
        f"Act {num}: {len(topics)} topic shifts ({', '.join(topics[:3])}...)"
        for num, topics in drifting_acts.items()
    ]
    detail = f"Topic drift in {len(drifting_acts)} act(s): {'; '.join(act_details)}"

    return False, drifting_acts, detail


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
    """Result of a single validation check.

    Advisory checks are logged but don't block the pipeline.
    """
    name: str
    passed: bool
    detail: str
    retry_prompt: str = ""
    advisory: bool = False  # Advisory checks warn but don't block


@dataclass
class ScriptValidationResult:
    """Aggregated result of all post-generation validation checks."""
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        # Advisory checks don't affect the overall pass/fail status
        return all(c.passed for c in self.checks if not c.advisory)

    @property
    def failed_checks(self) -> list[CheckResult]:
        # Advisory checks are excluded from blocking failures
        return [c for c in self.checks if not c.passed and not c.advisory]

    @property
    def advisory_warnings(self) -> list[CheckResult]:
        """Advisory checks that failed but don't block the pipeline."""
        return [c for c in self.checks if not c.passed and c.advisory]

    @property
    def summary(self) -> str:
        lines = []
        for c in self.checks:
            if c.passed:
                status = "PASS"
            elif c.advisory:
                status = "WARN"  # Advisory failures show as warnings
            else:
                status = "FAIL"
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
                    "advisory": c.advisory,
                }
                for c in self.checks
            ],
            "advisory_warnings": [c.name for c in self.advisory_warnings],
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
                f"VIEWER STAKES MISSING: Score {score}/{config.personal_stakes_min_score}. "
                f"The script talks ABOUT consequences but never addresses the "
                f"viewer directly or makes the stakes concrete for THEM.\n\n"
                f"SPECIFIC FIGURES FROM RESEARCH (use real ones, not placeholders):\n"
                f"  Prices/amounts: {price_examples}\n"
                f"  Percentages: {pct_examples}\n"
                f"  Quantities: {count_examples}\n\n"
                f"FIX:\n"
                f"  1. Open the stakes beat by turning to the viewer: 'Here's "
                f"what this means for you.'\n"
                f"  2. Translate at least one figure above into a concrete, "
                f"first-person consequence for the viewer — whatever is real "
                f"for THIS topic (cost, time, risk, effort, outcome), not a "
                f"fixed personal-finance frame.\n"
                f"  3. Use direct address ('you', 'your') so the viewer feels "
                f"the consequence rather than just hearing about it.\n\n"
                f"Pick the stakes that actually fit the subject — a story, a "
                f"recipe, and a market analysis each have very different stakes."
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
                f"Close with a concrete takeaway the viewer can ACT ON: a "
                f"decision, a thing to watch for, a step to take, or a signal "
                f"to monitor. Make it specific to THIS topic — don't force an "
                f"investing/markets frame onto a script that isn't about money."
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
        # Allow 3/5 — micro-insights and emotional beats are valid forward pulls
        min_required = max(expected - 2, 1) if expected > 0 else 0
        passed = found >= min_required if expected > 0 else True
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

    # --- Check 6: Promise-Payoff Tracking ---
    if config.promise_payoff_check:
        passed, broken_promises, detail = _check_promise_payoff(script, acts)

        retry_prompt = ""
        if not passed and broken_promises:
            promise_details = []
            for bp in broken_promises[:5]:  # Cap at 5 for readability
                promise_details.append(
                    f"  - Act {bp['act']}: \"{bp['text'][:100]}...\"\n"
                    f"    Issue: {bp['resolution_detail']}"
                )

            retry_prompt = (
                f"BROKEN_PROMISE: {len(broken_promises)} forward reference(s) "
                f"are not resolved in later acts.\n\n"
                f"UNRESOLVED PROMISES:\n"
                f"{chr(10).join(promise_details)}\n\n"
                f"FIX INSTRUCTIONS:\n"
                f"- For each broken promise, EITHER:\n"
                f"  a) Add the promised content to the referenced act, OR\n"
                f"  b) Remove or rewrite the promise so it doesn't tease "
                f"content that doesn't exist\n"
                f"- If a promise says 'Act 3 reveals...' and Act 3 doesn't "
                f"contain that content, ADD IT to Act 3\n"
                f"- Do NOT simply delete promises — they drive retention. "
                f"Prefer adding the payoff content.\n"
                f"- Each promise must have a clear payoff. Generic resolutions "
                f"like 'as we discussed' don't count."
            )

        result.checks.append(CheckResult(
            name="promise_payoff",
            passed=passed,
            detail=detail,
            retry_prompt=retry_prompt,
        ))

    # --- Check 7: Act Coherence (Topic Drift) ---
    if config.act_coherence_check:
        passed, drifting_acts, detail = _check_act_coherence(
            acts, max_topics_per_act=config.act_coherence_max_topics
        )

        retry_prompt = ""
        if not passed and drifting_acts:
            drift_details = []
            for act_num, topics in drifting_acts.items():
                drift_details.append(
                    f"  - Act {act_num}: {len(topics)} distinct topic shifts\n"
                    f"    Topics: {', '.join(topics[:4])}"
                )

            retry_prompt = (
                f"PACING_DRIFT: {len(drifting_acts)} act(s) contain too many "
                f"distinct topics (max {config.act_coherence_max_topics}).\n\n"
                f"DRIFTING ACTS:\n"
                f"{chr(10).join(drift_details)}\n\n"
                f"FIX INSTRUCTIONS:\n"
                f"- Each act should have ONE primary focus. When you introduce "
                f"a new subject, the viewer's attention resets.\n"
                f"- For acts with 3+ topics, choose the MOST important one "
                f"and cut or move the others to appropriate acts.\n"
                f"- If content must stay, bridge topics with explicit "
                f"connections: 'This same pattern — [topic A] — is why "
                f"[topic B] matters.'\n"
                f"- Move standalone paragraphs to acts where they fit the "
                f"primary narrative thread.\n"
                f"- Do NOT pad with transitions. Cut aggressively."
            )

        result.checks.append(CheckResult(
            name="act_coherence",
            passed=passed,
            detail=detail,
            retry_prompt=retry_prompt,
            advisory=True,  # Warns but doesn't block — geopolitics scripts naturally reference many entities
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
