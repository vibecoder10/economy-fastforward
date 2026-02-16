"""Title formulas for Economy FastForward videos.

Every title follows the structure:
    [Main Hook — 6-8 words, ONE CAPS word] (Parenthetical Reveal)

The CAPS word in the title MUST match the `red_word` in the thumbnail prompt.
This creates visual-verbal coherence between title and thumbnail.

Six formula families:
  1. trap     — The [Noun] TRAP Nobody Sees Coming
  2. country_dollar — [Country]'s $[Amount] [Noun] WEAPON
  3. slow_death — The Slow DEATH of [System]
  4. stronger_than — Why [Country] is [ADJECTIVE]er Than You Think
  5. list_warning — [Number] [Noun] [Warning]
  6. swallowed — How [Entity] SWALLOWED [Target]
"""

import re


# ---------------------------------------------------------------------------
# Title formula definitions
# ---------------------------------------------------------------------------
TITLE_FORMULAS = {
    "trap": {
        "pattern": "The {{noun}} {caps_word} Nobody Sees Coming ({{parenthetical}})",
        "examples": [
            "The Robot TRAP Nobody Sees Coming (A 4-Stage Monopoly)",
            "The Dollar TRAP Nobody Sees Coming (Why Cash Is a Weapon)",
            "The Housing TRAP Nobody Sees Coming (And Who Profits)",
        ],
    },
    "country_dollar": {
        "pattern": "{{country}}'s ${{amount}} {{noun}} {caps_word} ({{parenthetical}})",
        "examples": [
            "America's $34 Trillion Debt WEAPON (The Machiavellian Strategy)",
            "China's $3 Trillion Dollar TRAP (The Silent Economic War)",
            "Germany's $500 Billion MISTAKE (Why Green Energy Failed)",
        ],
    },
    "slow_death": {
        "pattern": "The Slow {caps_word} of {{system}} ({{parenthetical}})",
        "examples": [
            "The Slow DEATH of the Dollar (And Who Controls What Replaces It)",
            "The Slow COLLAPSE of NATO (And Russia's Play to Replace It)",
            "The Slow DEATH of the Middle Class (And Who's Engineering It)",
        ],
    },
    "stronger_than": {
        "pattern": "Why {{country}} is {caps_word} Than You Think ({{parenthetical}})",
        "examples": [
            "Why Russia is STRONGER Than You Think (The Machiavellian Energy Play)",
            "Why America is WEAKER Than You Think (The Hidden Debt Pattern)",
            "Why China is RICHER Than You Think (The Strategy Nobody Discusses)",
        ],
    },
    "list_warning": {
        "pattern": "{{number}} {{noun}} {caps_word} ({{parenthetical}})",
        "examples": [
            "7 Economic LIES They Need You to Believe (Machiavelli Warned You)",
            "5 Signs Your Country's Economy is DYING (The Pattern Repeats)",
            "9 Financial TRAPS Designed to Keep You Poor (The System Explained)",
        ],
    },
    "swallowed": {
        "pattern": "How {{entity}} {caps_word} {{target}} ({{parenthetical}})",
        "examples": [
            "How Blackrock SWALLOWED the Housing Market (The 3-Stage Playbook)",
            "How AI SWALLOWED Your Job Market (The 4-Stage Monopoly Trap)",
            "How Debt SWALLOWED the American Dream (The Machiavellian Design)",
        ],
    },
}


def generate_title(formula_key: str, title_vars: dict) -> str:
    """Generate a title from a formula and variables.

    The `title_vars` dict must contain all placeholder names used in the
    formula pattern PLUS `caps_word` which is inserted as the ALL-CAPS word.

    Args:
        formula_key: Key from TITLE_FORMULAS (e.g. "trap", "slow_death").
        title_vars: Dict of variables to fill the formula. Must include
            'caps_word' for the ALL-CAPS word that matches the thumbnail
            red_word.

    Returns:
        The formatted title string.

    Raises:
        KeyError: If formula_key is not found or required vars are missing.
    """
    if formula_key not in TITLE_FORMULAS:
        raise KeyError(
            f"Unknown title formula '{formula_key}'. "
            f"Available: {list(TITLE_FORMULAS.keys())}"
        )

    formula = TITLE_FORMULAS[formula_key]
    pattern = formula["pattern"]

    caps_word = title_vars.get("caps_word") or title_vars.get("CAPS_WORD", "")
    caps_word = caps_word.upper()

    # First replace {caps_word} in the pattern
    filled = pattern.replace("{caps_word}", caps_word)

    # Then replace {{var}} placeholders with title_vars values
    # Pattern uses {{var}} to distinguish from the {caps_word} placeholder
    for key, value in title_vars.items():
        if key in ("caps_word", "CAPS_WORD"):
            continue
        filled = filled.replace("{{" + key + "}}", str(value))

    # Verify no unfilled placeholders remain
    remaining = re.findall(r"\{\{(\w+)\}\}", filled)
    if remaining:
        raise KeyError(
            f"Missing title variables: {remaining}. "
            f"Provided: {list(title_vars.keys())}"
        )

    return filled


def extract_caps_word(title: str) -> str:
    """Extract the ALL-CAPS word from a title string.

    Finds the single word that is entirely uppercase (length >= 2),
    excluding common short words like "A", "I".

    Args:
        title: The full title string.

    Returns:
        The CAPS word, or empty string if none found.
    """
    # Get text before parenthetical (main hook)
    main_hook = title.split("(")[0] if "(" in title else title
    words = main_hook.split()
    for word in words:
        clean = word.strip("$,.'\"!?")
        if len(clean) >= 2 and clean.isupper() and clean.isalpha():
            return clean
    return ""
