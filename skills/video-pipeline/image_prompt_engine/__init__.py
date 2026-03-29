"""Compatibility shim for legacy ``image_prompt_engine`` imports.

The pipeline was renamed to ``image_prompts.engine`` during the StoryEngine
migration, but a few production call sites still import the old package name.
Re-export the public API here so older imports keep working until every caller
is updated.
"""

from image_prompts.engine import *  # noqa: F401,F403

