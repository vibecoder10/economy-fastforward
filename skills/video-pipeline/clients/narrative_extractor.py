"""Narrative field extraction from Research Payload.

Shared utility for extracting Past Context, Present Parallel, and Future Prediction
from various research payload formats. Used by:
- research_agent.py (deep research)
- discovery_scanner.py (competitor/news scraping)
- trending_idea_bot.py (trending topic modeling)

All three entry points call this function to ensure consistent field population.
"""

import re
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def extract_narrative_fields(
    research_payload: dict,
    anthropic_client=None,
) -> dict:
    """Extract Past Context, Present Parallel, Future Prediction from research data.

    Args:
        research_payload: Dict containing research fields like historical_parallels,
            narrative_arc, framework_analysis, thesis, etc.
        anthropic_client: Optional AnthropicClient for generating Future Prediction
            via Claude Haiku if not enough data exists.

    Returns:
        Dict with keys:
            - past_context: 2-3 sentence summary of strongest historical parallel
            - present_parallel: 2-3 sentence summary of current situation
            - future_prediction: 2-3 sentence actionable prediction
    """
    past_context = _extract_past_context(research_payload)
    present_parallel = _extract_present_parallel(research_payload)
    future_prediction = _extract_future_prediction(research_payload, anthropic_client)

    return {
        "past_context": past_context,
        "present_parallel": present_parallel,
        "future_prediction": future_prediction,
    }


def _extract_past_context(payload: dict) -> str:
    """Extract the strongest historical parallel as Past Context.

    Sources (in priority order):
    1. historical_parallels — full research section
    2. historical_parallel_hint — discovery scanner hint
    3. narrative_arc — look for historical references

    Returns 2-3 sentence summary of the key historical precedent.
    """
    # Primary source: historical_parallels from research
    hist = payload.get("historical_parallels", "")
    if hist and len(hist.strip()) > 50:
        return _summarize_to_sentences(hist, max_sentences=3, prefix="Historical: ")

    # Fallback: discovery scanner hint
    hint = payload.get("historical_parallel_hint", "")
    if hint and len(hint.strip()) > 20:
        return hint.strip()

    # Fallback: extract from narrative_arc
    arc = payload.get("narrative_arc", "")
    if arc:
        # Look for historical references in narrative arc
        historical_section = _extract_section(arc, ["HISTORICAL", "BACKGROUND", "CONTEXT", "PAST"])
        if historical_section:
            return _summarize_to_sentences(historical_section, max_sentences=3)

    return ""


def _extract_present_parallel(payload: dict) -> str:
    """Extract the current situation as Present Parallel.

    Sources (in priority order):
    1. narrative_arc — "WHAT HAPPENED" or "CURRENT" section
    2. thesis — core argument about current state
    3. executive_hook — opening hook describes current situation

    Returns 2-3 sentence summary of current situation with dates/numbers.
    """
    arc = payload.get("narrative_arc", "")
    if arc:
        # Look for current situation section
        current_section = _extract_section(
            arc,
            ["WHAT HAPPENED", "CURRENT", "NOW", "TODAY", "PRESENT", "SITUATION"]
        )
        if current_section:
            return _summarize_to_sentences(current_section, max_sentences=3)

    # Fallback: thesis often describes the current situation
    thesis = payload.get("thesis", "")
    if thesis and len(thesis.strip()) > 50:
        return _summarize_to_sentences(thesis, max_sentences=3)

    # Fallback: executive hook
    hook = payload.get("executive_hook", "")
    if hook and len(hook.strip()) > 50:
        return _summarize_to_sentences(hook, max_sentences=2)

    # Fallback: our_angle from discovery scanner
    angle = payload.get("our_angle", "")
    if angle and len(angle.strip()) > 20:
        return angle.strip()

    return ""


def _extract_future_prediction(payload: dict, anthropic_client=None) -> str:
    """Extract actionable prediction as Future Prediction.

    Sources (in priority order):
    1. narrative_arc — "WHAT HAPPENS NEXT" or "FUTURE" section
    2. counter_arguments — often contains predictions
    3. Claude Haiku generation — if no data, generate from thesis + framework

    Returns 2-3 sentence actionable prediction.
    """
    arc = payload.get("narrative_arc", "")
    if arc:
        # Look for future/prediction section
        future_section = _extract_section(
            arc,
            ["WHAT HAPPENS NEXT", "FUTURE", "PREDICTION", "IMPLICATIONS", "WHAT THIS MEANS", "OUTCOME"]
        )
        if future_section:
            return _summarize_to_sentences(future_section, max_sentences=3)

    # Fallback: counter_arguments may contain predictions
    counter = payload.get("counter_arguments", "")
    if counter and len(counter.strip()) > 100:
        # Look for prediction-like language
        prediction_match = _extract_prediction_language(counter)
        if prediction_match:
            return prediction_match

    # Fallback: Generate via Claude Haiku if we have thesis + framework
    thesis = payload.get("thesis", "")
    framework = payload.get("framework_analysis", "")
    if anthropic_client and thesis and len(thesis) > 30:
        return _generate_future_prediction(anthropic_client, thesis, framework, payload)

    return ""


def _extract_section(text: str, section_markers: list[str]) -> str:
    """Extract a section from text based on header markers.

    Looks for patterns like:
    - "## WHAT HAPPENED"
    - "WHAT HAPPENED:"
    - "**What Happened**"
    """
    text_upper = text.upper()

    for marker in section_markers:
        marker_upper = marker.upper()

        # Try markdown header pattern: ## MARKER or # MARKER
        header_pattern = rf"#+\s*{re.escape(marker_upper)}[:\s]*\n(.*?)(?=\n#+|\Z)"
        match = re.search(header_pattern, text_upper, re.DOTALL)
        if match:
            start = match.start(1)
            end = match.end(1)
            return text[start:end].strip()

        # Try colon pattern: MARKER:
        colon_pattern = rf"{re.escape(marker_upper)}:\s*(.*?)(?=\n[A-Z][A-Z\s]+:|\Z)"
        match = re.search(colon_pattern, text_upper, re.DOTALL)
        if match:
            start = match.start(1)
            end = match.end(1)
            return text[start:end].strip()

    return ""


def _extract_prediction_language(text: str) -> str:
    """Extract sentences with prediction language from text."""
    prediction_patterns = [
        r"[^.]*(?:will\s+(?:likely|probably|eventually)|going\s+to|expect\s+to|could\s+lead\s+to|may\s+result\s+in|this\s+means)[^.]*\.",
        r"[^.]*(?:in\s+the\s+(?:coming|next)|by\s+\d{4}|within\s+\d+\s+(?:months?|years?))[^.]*\.",
    ]

    for pattern in prediction_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            # Return first 2-3 prediction sentences
            return " ".join(matches[:2]).strip()

    return ""


def _summarize_to_sentences(text: str, max_sentences: int = 3, prefix: str = "") -> str:
    """Summarize text to first N complete sentences.

    Cleans up the text and returns the most relevant sentences.
    """
    # Clean up text
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^[-•*]\s*', '', text)  # Remove bullet points

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

    if not sentences:
        return ""

    result = " ".join(sentences[:max_sentences])

    # Add prefix if provided and result doesn't already have context
    if prefix and not result.lower().startswith(prefix.lower().split(":")[0].lower()):
        return f"{prefix}{result}"

    return result


def _generate_future_prediction(
    anthropic_client,
    thesis: str,
    framework: str,
    payload: dict,
) -> str:
    """Generate Future Prediction via Claude Haiku.

    Cost: ~$0.001 per call. Called only when extraction fails.
    """
    try:
        # Build context from available fields
        context_parts = [f"Thesis: {thesis}"]
        if framework:
            context_parts.append(f"Framework: {framework[:500]}")
        headline = payload.get("headline", "")
        if headline:
            context_parts.append(f"Topic: {headline}")

        context = "\n".join(context_parts)

        prompt = f"""Based on this analysis, write 2-3 sentences predicting what happens next.
Focus on:
1. Specific outcomes (with timeframes if possible)
2. Who benefits and who loses
3. What viewers should watch for

Context:
{context}

Write ONLY the prediction (2-3 sentences, no preamble):"""

        # Use haiku for cost efficiency
        result = anthropic_client.generate_sync(
            prompt=prompt,
            model="claude-3-5-haiku-20241022",
            max_tokens=200,
            temperature=0.7,
        )

        if result and len(result.strip()) > 30:
            return result.strip()

    except Exception as e:
        logger.warning(f"Future prediction generation failed: {e}")

    return ""


def extract_narrative_fields_from_concept(concept: dict) -> dict:
    """Extract narrative fields from a trending/discovery concept dict.

    Used by trending_idea_bot.py and discovery_scanner.py when processing
    AI-generated concepts that may already have narrative_logic populated.

    Args:
        concept: Concept dict with potential narrative_logic, hook_script, etc.

    Returns:
        Dict with past_context, present_parallel, future_prediction
    """
    # Check if concept already has narrative_logic
    narrative = concept.get("narrative_logic", {})
    if isinstance(narrative, dict):
        past = narrative.get("past_context", "")
        present = narrative.get("present_parallel", "")
        future = narrative.get("future_prediction", "")

        # If we have all three fields populated, return them
        if past and present and future:
            return {
                "past_context": past.strip(),
                "present_parallel": present.strip(),
                "future_prediction": future.strip(),
            }

    # Otherwise, try to extract from other fields
    return {
        "past_context": narrative.get("past_context", "") if isinstance(narrative, dict) else "",
        "present_parallel": (
            narrative.get("present_parallel", "")
            if isinstance(narrative, dict)
            else concept.get("our_angle", "")
        ),
        "future_prediction": (
            narrative.get("future_prediction", "")
            if isinstance(narrative, dict)
            else ""
        ),
    }
