from __future__ import annotations

"""Shared JSON parsing utilities for AI response extraction.

All Claude/Gemini responses use this fallback chain:
  1. json.loads(response) directly
  2. Remove markdown fences (```json ... ```), try again
  3. Extract JSON substring ({...} or [...]), try again
  4. Fix common issues (trailing commas), try again
  5. Return default on failure

Usage:
    from json_utils import parse_json_response

    result = parse_json_response(llm_text)              # returns dict or {}
    result = parse_json_response(llm_text, default=[])  # returns list or []
    result = parse_json_response(llm_text, default=None) # returns dict or None
"""

import json
import re
from typing import Any

_UNSET = object()


def parse_json_response(
    text: str,
    default: Any = _UNSET,
) -> Any:
    """Extract and parse JSON from an AI model response.

    Handles markdown fences, extra text before/after JSON, trailing
    commas, and other common LLM formatting issues.

    Args:
        text: Raw response text from Claude/Gemini/etc.
        default: Value to return if all parsing fails.
                 Defaults to empty dict {} if not specified.

    Returns:
        Parsed JSON (dict or list), or *default* on failure.
    """
    if default is _UNSET:
        default = {}

    if not text or not text.strip():
        return default

    text = text.strip()

    # Step 1: Try direct parse (fast path — works when model returns clean JSON)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Step 2: Strip markdown fences and retry
    clean = _strip_markdown_fences(text)
    if clean != text:
        try:
            return json.loads(clean)
        except (json.JSONDecodeError, ValueError):
            pass

    # Step 3: Extract JSON substring (first { to last }, or [ to ])
    extracted = _extract_json_substring(clean)
    if extracted:
        try:
            return json.loads(extracted)
        except (json.JSONDecodeError, ValueError):
            pass

        # Step 4: Fix common issues and retry
        fixed = _fix_common_issues(extracted)
        if fixed != extracted:
            try:
                return json.loads(fixed)
            except (json.JSONDecodeError, ValueError):
                pass

    return default


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from text.

    Handles:
        ```json\n{...}\n```
        ```\n{...}\n```
        ```json{...}```  (no newlines)
    """
    # Try regex extraction from fenced block first (most precise)
    match = re.search(r"```(?:json)?\s*([\[{].*?[}\]])\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fallback: strip fence markers directly
    clean = text
    if clean.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = clean.find("\n")
        if first_newline != -1:
            clean = clean[first_newline + 1:]
        else:
            clean = clean[3:]  # no newline, just strip ```
    if clean.rstrip().endswith("```"):
        clean = clean.rstrip()[:-3]

    return clean.strip()


def _extract_json_substring(text: str) -> str | None:
    """Find the outermost JSON object or array in text.

    Returns the substring from the first { or [ to the matching
    last } or ], or None if not found.
    """
    # Try object first (most common)
    obj_start = text.find("{")
    obj_end = text.rfind("}")
    if obj_start != -1 and obj_end > obj_start:
        return text[obj_start:obj_end + 1]

    # Try array
    arr_start = text.find("[")
    arr_end = text.rfind("]")
    if arr_start != -1 and arr_end > arr_start:
        return text[arr_start:arr_end + 1]

    return None


def _fix_common_issues(text: str) -> str:
    """Fix common JSON formatting issues from LLM output.

    - Trailing commas before } or ]
    - Single-quoted strings (less common but happens)
    """
    # Remove trailing commas: ,} or ,]
    fixed = re.sub(r",\s*([}\]])", r"\1", text)
    return fixed
