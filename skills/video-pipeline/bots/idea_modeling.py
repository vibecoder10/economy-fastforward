"""
Idea Modeling Module — Variable Decomposition & Format Modeling (v2)

This module upgrades idea generation from surface-level topic imitation
to a two-layer modeling framework:
  1. Model the Ideal — classify the psychological trigger (why it won)
  2. Model the Format — extract the reusable title structure as typed variables

Core functions:
  - decompose_title(): Break a title into typed variables + triggers
  - extract_format(): Group decomposed titles into reusable format patterns
  - generate_modeled_ideas(): Rebuild proven formats with niche variables
  - update_format_library(): Persist new formats to config for compounding
"""

import json
from pathlib import Path
from typing import Optional


CONFIG_PATH = Path(__file__).parent.parent / "config" / "idea_modeling_config.json"

DECOMPOSE_SYSTEM_PROMPT = """You are a YouTube title analyst. Given a video title, decompose it into typed variables.

Variable types:
- number: A concrete number (7, 30, Top 10)
- authority_qualifier: Credibility word (Most, Best, Expert)
- core_topic: The main subject noun
- extreme_benefit: The big promise or consequence
- specific_mechanism: The concrete detail that grounds it
- time_anchor: Temporal element (In 2026, Right Now)
- target_audience: Who this is for (For Beginners, Every American)

Also classify which psychological triggers this title uses:
longevity, fear, practical_value, curiosity_gap, authority, urgency, contrarian, aspiration, outrage, scale

Respond in JSON only. No markdown, no explanation.

Example input: "30 Most Reliable Cars with FOREVER LASTING ENGINES!"
Example output:
{
  "variables": {
    "number": "30",
    "authority_qualifier": "Most Reliable",
    "core_topic": "Cars",
    "extreme_benefit": "Forever Lasting",
    "specific_mechanism": "Engines"
  },
  "formula": "[Number] + [Authority Qualifier] + [Core Topic] + [Extreme Benefit] + [Specific Mechanism]",
  "psychological_triggers": ["longevity", "practical_value", "scale"]
}"""

GENERATE_IDEAS_SYSTEM_PROMPT = """You are the Executive Producer for 'Economy Fast-Forward', a faceless YouTube channel.

You will be given:
1. PROVEN FORMATS extracted from high-performing YouTube videos
2. NICHE VARIABLES for the economy/finance niche

Your job: Take each proven format and rebuild it using the niche variables.

RULES:
- Swap 1-2 variables max from each format
- Synonym swaps don't count — the replacement must change the actual content
- Keep the structural formula intact
- For each idea, explain which format it's based on and what was swapped
- Classify the psychological triggers
- Use specific numbers, years, or dollar amounts
- ALL CAPS for 1-2 words max
- Future dates perform well (2026, 2027, 2030)

Return a JSON object with a "ideas" array. No markdown, no explanation."""


def load_config() -> dict:
    """Load the idea modeling config from disk."""
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(config: dict) -> None:
    """Write updated config back to disk (atomic-ish)."""
    tmp_path = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    tmp_path.replace(CONFIG_PATH)


async def decompose_title(title: str, anthropic_client, views: int = 0) -> dict:
    """Decompose a YouTube title into typed variables and psychological triggers.

    Args:
        title: The YouTube video title
        anthropic_client: AnthropicClient instance (uses .generate())
        views: View count for this video (attached to output)

    Returns:
        Dict with original_title, variables, formula, psychological_triggers
    """
    user_prompt = f'Decompose this YouTube title into variables:\n\n"{title}"'

    try:
        response = await anthropic_client.generate(
            prompt=user_prompt,
            system_prompt=DECOMPOSE_SYSTEM_PROMPT,
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            temperature=0.2,
        )

        clean = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)

        return {
            "original_title": title,
            "views": views,
            "variables": data.get("variables", {}),
            "formula": data.get("formula", ""),
            "psychological_triggers": data.get("psychological_triggers", []),
        }
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  ⚠️ Failed to decompose title: {title[:50]}... ({e})")
        return {
            "original_title": title,
            "views": views,
            "variables": {},
            "formula": "",
            "psychological_triggers": [],
        }
    except Exception as e:
        print(f"  ❌ API error decomposing title: {title[:50]}... ({e})")
        return {
            "original_title": title,
            "views": views,
            "variables": {},
            "formula": "",
            "psychological_triggers": [],
        }


def _normalize_formula(formula: str) -> str:
    """Normalize a formula string for comparison.

    Strips whitespace, lowercases, and removes extra punctuation so that
    "[Number] + [Core Topic] + [Extreme Benefit]" matches
    "[number] + [core_topic] + [extreme_benefit]".
    """
    import re
    # Extract bracketed variable names
    parts = re.findall(r"\[([^\]]+)\]", formula.lower())
    # Normalize each part: strip, replace spaces/underscores
    normalized = [p.strip().replace(" ", "_") for p in parts]
    return " + ".join(f"[{p}]" for p in normalized)


def extract_format(decomposed_titles: list[dict]) -> list[dict]:
    """Group decomposed titles by similar formula patterns into reusable formats.

    Args:
        decomposed_titles: List of dicts from decompose_title()

    Returns:
        List of format dicts with format_id, formula, example_titles, etc.
    """
    # Filter out failed decompositions
    valid = [d for d in decomposed_titles if d.get("formula")]

    # Group by normalized formula
    groups: dict[str, list[dict]] = {}
    for item in valid:
        key = _normalize_formula(item["formula"])
        if key not in groups:
            groups[key] = []
        groups[key].append(item)

    formats = []
    for i, (norm_formula, items) in enumerate(groups.items()):
        # Use the first item's raw formula as the display formula
        display_formula = items[0]["formula"]
        titles = [it["original_title"] for it in items]
        views = [it.get("views", 0) for it in items]
        avg_views = int(sum(views) / len(views)) if views else 0

        # Build a readable format_id from the formula variables
        parts = norm_formula.replace("[", "").replace("]", "").split(" + ")
        format_id = "_".join(parts[:3]) if parts else f"format_{i}"

        formats.append({
            "format_id": format_id,
            "formula": display_formula,
            "normalized_formula": norm_formula,
            "example_titles": titles,
            "times_seen": len(items),
            "avg_views": avg_views,
        })

    # Sort by times_seen desc, then avg_views desc
    formats.sort(key=lambda f: (f["times_seen"], f["avg_views"]), reverse=True)

    return formats


async def generate_modeled_ideas(
    formats: list[dict],
    config: dict,
    anthropic_client,
    num_ideas: int = 5,
) -> list[dict]:
    """Generate new video ideas by rebuilding proven formats with niche variables.

    Args:
        formats: List of format dicts from extract_format()
        config: The idea_modeling_config dict (contains niche_variables)
        anthropic_client: AnthropicClient instance
        num_ideas: Number of ideas to generate

    Returns:
        List of idea dicts with viral_title, format attribution, swap docs, triggers
    """
    niche = config.get("niche_variables", {})
    triggers_ref = config.get("psychological_triggers", [])

    # Build the format descriptions for the prompt
    format_descriptions = []
    for fmt in formats[:10]:  # Cap at 10 formats to keep prompt reasonable
        desc = (
            f"Format: {fmt['formula']}\n"
            f"  Example: \"{fmt['example_titles'][0]}\"\n"
            f"  Times seen: {fmt['times_seen']}, Avg views: {fmt['avg_views']:,}"
        )
        format_descriptions.append(desc)

    trigger_descriptions = "\n".join(
        f"- {t['id']}: {t['description']}" for t in triggers_ref
    )

    user_prompt = f"""Generate exactly {num_ideas} video ideas using these proven formats and niche variables.

## PROVEN FORMATS (from high-performing videos):
{chr(10).join(format_descriptions)}

## NICHE VARIABLES:
- Channel: {niche.get('channel_name', 'Economy FastForward')}
- Core topics: {', '.join(niche.get('core_topics', []))}
- Audience: {niche.get('audience', '')}

## PSYCHOLOGICAL TRIGGERS REFERENCE:
{trigger_descriptions}

## OUTPUT FORMAT:
Return a JSON object:
{{
  "ideas": [
    {{
      "viral_title": "The YouTube title",
      "based_on_format": "format_id from the list above",
      "original_example": "The example title this is based on",
      "variables_swapped": ["variable: OldValue→NewValue", ...],
      "psychological_triggers": ["trigger_id", ...],
      "hook_summary": "One sentence: why this works psychologically"
    }}
  ]
}}

Generate {num_ideas} ideas. Each should use a DIFFERENT format. No markdown, JSON only."""

    try:
        response = await anthropic_client.generate(
            prompt=user_prompt,
            system_prompt=GENERATE_IDEAS_SYSTEM_PROMPT,
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            temperature=0.9,
        )

        clean = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
        ideas = data.get("ideas", [])

        return ideas

    except (json.JSONDecodeError, KeyError) as e:
        print(f"  ⚠️ Failed to parse modeled ideas response: {e}")
        return []
    except Exception as e:
        print(f"  ❌ API error generating modeled ideas: {e}")
        return []


def update_format_library(new_formats: list[dict], config: dict) -> dict:
    """Merge newly discovered formats into the persistent format library.

    If a format with the same normalized formula exists, increment times_seen
    and add new example titles. If new, append it.

    Args:
        new_formats: List of format dicts from extract_format()
        config: The full config dict (mutated in place and returned)

    Returns:
        The updated config dict
    """
    library = config.get("format_library", [])

    # Index existing library by normalized formula for fast lookup
    existing: dict[str, dict] = {}
    for entry in library:
        key = entry.get("normalized_formula", _normalize_formula(entry.get("formula", "")))
        existing[key] = entry

    for fmt in new_formats:
        norm = fmt.get("normalized_formula", _normalize_formula(fmt.get("formula", "")))
        if not norm:
            continue

        if norm in existing:
            # Update existing entry
            entry = existing[norm]
            entry["times_seen"] = entry.get("times_seen", 0) + fmt.get("times_seen", 1)
            # Add new example titles (deduplicated)
            current_examples = set(entry.get("example_titles", []))
            for title in fmt.get("example_titles", []):
                if title not in current_examples:
                    entry.setdefault("example_titles", []).append(title)
                    current_examples.add(title)
            # Update avg_views as weighted average
            old_seen = entry.get("times_seen", 1) - fmt.get("times_seen", 1)
            if old_seen + fmt.get("times_seen", 1) > 0:
                entry["avg_views"] = int(
                    (entry.get("avg_views", 0) * old_seen + fmt.get("avg_views", 0) * fmt.get("times_seen", 1))
                    / (old_seen + fmt.get("times_seen", 1))
                )
        else:
            # New format — add to library
            new_entry = {
                "format_id": fmt.get("format_id", "unknown"),
                "formula": fmt.get("formula", ""),
                "normalized_formula": norm,
                "example_titles": fmt.get("example_titles", []),
                "times_seen": fmt.get("times_seen", 1),
                "avg_views": fmt.get("avg_views", 0),
            }
            library.append(new_entry)
            existing[norm] = new_entry

    # Sort library by times_seen desc
    library.sort(key=lambda f: (f.get("times_seen", 0), f.get("avg_views", 0)), reverse=True)

    config["format_library"] = library
    return config
