"""Functional test for C35 (P3.4, docs/reports/2026-07-17-storyengine-agent
-audit-findings.md Sweep 2 finding 4 / tasks/storyengine-wiring-fix-checklist.md
§3.4): the Claude text-model tier map used to be duplicated independently at
~15+ call sites across storyengine/backend (routes/chat.py, routes/videos.py,
routes/model_video.py, producer_prompt.py, static_docu.py, identity_builder.py,
user_script.py, script_templates.py, routes/pipeline.py, youtube_publish.py,
distillation/*.py, coverage_to_app.py, originality.py, routes/system_prompts.py,
routes/youtube_channel.py, claude_orchestrator.py, kie_unified.py) instead of
reading one shared map — bumping a Claude version meant grep-and-pray across
the whole backend, and two of those independent copies
("claude-sonnet-4-20250514" in claude_orchestrator.py / routes/system_prompts.py
/ routes/youtube_channel.py) had drifted to a stale id that 404s on the live
Anthropic API, a genuine live bug, not just duplication.

The fix: `shared.channel_profile.CLAUDE_MODELS` (next to MODEL_REGISTRY,
mirroring the C09 single-price-source pattern) is now the one source. Every
call site imports it (directly, or via actions.py's re-export) instead of
carrying its own literal. `claude_model_for_direct_client()` replaces the
repeated `"claude-sonnet-4-6" if type(client).__name__ ==
"AnthropicDirectClient" else None` idiom.

This test pins the fix three ways:
  1. The single source exists with the expected shape and values.
  2. actions.py re-exports it (the same path every existing PICTURE_COST /
     CLIP_COST consumer already uses).
  3. Static audit: no OTHER file under storyengine/backend hardcodes one of
     the canonical tier-map literal strings, except a documented allowlist —
     kie_unified.py (the Kie-alias TRANSLATION table, a different concern:
     mapping arbitrary caller-supplied ids to whatever Kie's gateway
     currently accepts, not a tier choice) and canaries/ (drift probes that
     must pin a version on purpose to detect when Anthropic changes it,
     the opposite of following a shared "current tier" pointer).
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Importing actions.py first is what puts skills/video-pipeline (and hence
# `shared.*`) on sys.path — the same side effect every other backend module
# in this chunk relies on instead of re-deriving the path itself.
import actions  # noqa: E402,F401

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The canonical tier-map values (must match shared.channel_profile.CLAUDE_MODELS
# exactly — test 1 below cross-checks that, this list is just what the static
# audit greps for).
_CANONICAL_LITERALS = [
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-sonnet-4-20250514",  # the stale id the audit found 404ing
]

# Directories never scanned: virtualenv/deps, tests (which legitimately
# assert on the resolved value), migrations (SQL, not Python), caches.
_SKIP_DIR_NAMES = {"venv", "__pycache__", "tests", "migrations", ".git", "node_modules"}

# Files allowed to carry a literal independently of the single source, with
# the documented reason (see module docstring). Paths relative to
# storyengine/backend/.
_ALLOWED_FILES = {
    "kie_unified.py",  # Kie-alias translation table — different concern
    os.path.join("canaries", "validator_drift.py"),  # drift probe, pins on purpose
    os.path.join("canaries", "vision_drift.py"),      # drift probe, pins on purpose
}


def _iter_backend_py_files():
    for dirpath, dirnames, filenames in os.walk(BACKEND_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        rel_dir = os.path.relpath(dirpath, BACKEND_ROOT)
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            rel_path = fname if rel_dir == "." else os.path.join(rel_dir, fname)
            yield rel_path, os.path.join(dirpath, fname)


def test_canonical_map_shape_and_values():
    from shared.channel_profile import CLAUDE_MODELS, claude_model_for_direct_client

    assert set(CLAUDE_MODELS.keys()) == {"kie", "anthropic"}
    for provider, tiers in CLAUDE_MODELS.items():
        assert set(tiers.keys()) == {"smart", "fast"}, f"{provider} tiers"

    assert CLAUDE_MODELS["anthropic"]["smart"] == "claude-sonnet-4-6"
    assert CLAUDE_MODELS["anthropic"]["fast"] == "claude-haiku-4-5-20251001"
    assert CLAUDE_MODELS["kie"]["smart"] == "claude-sonnet-4-5"
    assert CLAUDE_MODELS["kie"]["fast"] == "claude-haiku-4-5"

    # The direct-client helper: None for anything that isn't literally an
    # AnthropicDirectClient instance (Kie-wrapped clients keep their own
    # default), the "smart" tier's Anthropic id otherwise.
    class _FakeKieClient:
        pass

    class AnthropicDirectClient:
        pass

    assert claude_model_for_direct_client(_FakeKieClient()) is None
    assert claude_model_for_direct_client(AnthropicDirectClient()) == "claude-sonnet-4-6"
    assert claude_model_for_direct_client(AnthropicDirectClient(), tier="fast") == "claude-haiku-4-5-20251001"


def test_actions_reexports_the_single_source():
    import actions

    from shared.channel_profile import CLAUDE_MODELS, claude_model_for_direct_client

    assert actions.CLAUDE_MODELS is CLAUDE_MODELS
    assert actions.claude_model_for_direct_client is claude_model_for_direct_client


def test_no_other_backend_file_hardcodes_the_tier_literals():
    """Static audit: grep every backend .py file (outside the allowlist) for
    the canonical literal strings. A hit means a new call site duplicated
    the tier map instead of importing CLAUDE_MODELS / claude_model_for_direct_client
    — exactly the bug this chunk fixed, reintroduced."""
    violations: list[str] = []

    for rel_path, abs_path in _iter_backend_py_files():
        if rel_path in _ALLOWED_FILES:
            continue
        try:
            with open(abs_path, encoding="utf-8") as f:
                source = f.read()
        except (UnicodeDecodeError, OSError):
            continue

        for literal in _CANONICAL_LITERALS:
            if literal not in source:
                continue
            # Only a genuine string-literal occurrence counts — a comment or
            # docstring mentioning the model name for documentation purposes
            # (e.g. originality.py's docstring) is not a duplicated call
            # site. Parse and check string constants specifically.
            try:
                tree = ast.parse(source, filename=abs_path)
            except SyntaxError:
                violations.append(f"{rel_path}: unparsable, contains {literal!r}")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if literal in node.value and node.value != literal:
                        # substring inside a longer string (e.g. a docstring
                        # sentence) — not a bare model-id literal, skip.
                        continue
                    if node.value == literal:
                        violations.append(
                            f"{rel_path}:{node.lineno}: hardcodes {literal!r} — "
                            "import CLAUDE_MODELS / claude_model_for_direct_client "
                            "from shared.channel_profile (or actions.py's re-export) instead"
                        )

    assert not violations, (
        "New/uncovered Claude tier literal(s) found outside the single source "
        "and its documented allowlist:\n  " + "\n  ".join(violations)
    )
