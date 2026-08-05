"""D15-5: the ONE canonical material/environment-locks precedence builder.

Before this module, the same "canonical DB row wins over the planner LLM's
own prose" logic existed as two hand-maintained copies:

  * assembler A (SHEET path, the $0.05 board-sheet PREVIEW):
    storyengine/backend/scripts/coverage_to_app.py's
    `_canonical_material_line` + `_env_locks_text` + `_canonical_
    environment_locks_line` — computed ONCE per scene, fed into
    `_sheet_kwargs` -> `_plan_sheet_prompts`, which wraps the raw clause
    into its own bracketed block header
    ("\\nMATERIAL MAP — fixed for this whole set: ...\\n").

  * assembler B (FRAME path, the real per-shot draw prompts):
    skills/video-pipeline/storyboard/coverage.py's `canonical_material_line`
    + `_env_locks_text` + `canonical_environment_locks_line` — computed
    ONCE per scene inside `run_coverage`, then STAMPED as an inline
    sentence tail onto every shot's own description
    ("Material map, fixed for this whole set: ... .").

D9-3b's own docstring already admitted these were "kept in sync by hand
rather than imported" because of the import direction: coverage_to_app.py
imports FROM storyboard.coverage (see its own `from storyboard.coverage
import (...)`), never the reverse, so assembler A could import a shared
helper defined here but assembler B could not import one defined in
coverage_to_app.py. This module breaks the deadlock by living in
storyboard/ (the side coverage_to_app.py already imports from) — both
assemblers now import the SAME functions from HERE.

RECONCILIATION (the diff between the two copies, found via an AST-level
diff of both bodies before any edits — see storyengine/backend/tests/
functional/test_d15_5_shot_context_goldens.py for the before/after golden
proof): exactly ONE semantic difference existed, in the `_find` closure's
None-handling —

  * assembler A's `envs` parameter was typed `list[dict]` (non-Optional)
    and iterated directly (`for e in envs`) — every real call site always
    passes a real list (`_approved_envs` returns `[]` on any failure,
    never None), so this was never observed to crash, but the CONTRACT was
    stricter than necessary.
  * assembler B's `canonical_envs` parameter was typed `list | None` and
    guarded (`for e in (canonical_envs or [])`) — `run_coverage`'s own
    default is `canonical_envs=None` (every caller before D6-1c, and the
    CLI's `main()`), so B genuinely needs the None-safety.

Reconciled to the STRICTER-CORRECT (safer superset) behavior: this module's
`envs` parameter accepts `list[dict] | None` and is None-safe throughout,
matching assembler B's existing, already-tested contract
(test_board_laws.py's `canonical_material_line(None, {"Pod": "..."}, None)
== ""` pins this). This is a pure widening — assembler A's call sites
always pass a real list, so its behavior is byte-identical before and
after. No other reconciliation was needed: `_env_locks_text`'s join-skip-
empty body was ALREADY byte-identical in both copies, and the material/
locks precedence bodies were byte-identical apart from the None-guard
above (confirmed by diffing both ASTs with docstrings stripped).

Everything else documented below was already true of BOTH copies and is
preserved verbatim:

  * D6-6e (whole-word LOCSET matching): a LOCSET key phrased with a leading
    article or extra prose ("The Elite Viewing Hall") must still resolve to
    its own approved environment's canonical row — exact-equality-after-
    normalization is not enough. `_find` matches by checking the approved
    environment's normalized name appears as a whole, space-padded phrase
    WITHIN the LOCSET key's normalized text (`f" {n} " in f" {padded} "`),
    not by requiring the two to be identical. A LOCSET key that names a
    location with NO approved environment at all still correctly finds
    nothing (whole-word, not substring — "pod" doesn't accidentally match
    "podium").
  * Multi-location scenes (location_sets non-empty): one verbatim clause per
    LOCSET name that has a matching approved environment with the relevant
    field populated, joined with a single space, each clause prefixed
    "NAME: ...". A location with no canonical entry is simply OMITTED from
    the combined string — a KNOWN GAP, not a bug: mixing a canonical clause
    for one location and an LLM-prose clause for a sibling location in the
    SAME block would itself violate "once, from one source of truth."
  * Single-location scenes (location_sets empty): `matched_env`'s own field,
    or "" if it has none or nothing matched.
  * Lock precedence (D9-2/D9-3): `env_locks_text` joins architecture_lock +
    lighting_time_weather_lock + palette_lock with "; ", skipping whichever
    of the three is empty/NULL — a partial extraction (only some of the
    three parsed) still contributes what it has, never blocked on the
    others being present. "" when none are populated, the byte-compat
    sentinel every caller's `if env_locks_line:` treats as "omit the
    block."
  * Never invents: both builders return "" (never fabricate prose) when no
    canonical entry exists anywhere relevant — callers keep their own
    existing prose-fallback behavior (assembler A/B's `_canonical_material
    or (parse_material_map(...) or "")`) unchanged.

`mode` parameter: accepted and validated ("sheet" | "frame") for callsite
self-documentation and as an explicit extension point, but does NOT change
either function's return value today — both consumption contexts need the
IDENTICAL canonical-precedence clause; only how each caller WRAPS that raw
clause into its own final prose differs (sheet: bracketed block header
built by `_plan_sheet_prompts`; frame: inline sentence tail built by
`run_coverage`), and that wrapping deliberately stays in each caller since
the two prose shapes are genuinely different, not drifted copies of one
shape. If a real per-mode difference is ever needed, `mode` is already
threaded through every call site to carry it — the alternative (forking
back into two hand-copied functions) is exactly what this module exists to
prevent.
"""
from __future__ import annotations

import re
from typing import Optional

VALID_MODES = ("sheet", "frame")

_ENV_NAME_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _check_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise ValueError(f"shot_context mode must be one of {VALID_MODES!r}, got {mode!r}")


def norm_env_name(s: Optional[str]) -> str:
    """Lowercase and collapse punctuation/dashes to single spaces, so
    'Home Kitchen — Cram Session' matches 'home kitchen - cram session'.
    Byte-identical to both prior copies (coverage_to_app._norm_env_text /
    coverage.py's own _norm_env_name)."""
    return _ENV_NAME_STRIP_RE.sub(" ", (s or "").lower()).strip()


def env_locks_text(row: dict) -> str:
    """D9-3 (migration 152): join an environment row's architecture_lock +
    lighting_time_weather_lock + palette_lock into ONE verbatim clause,
    skipping whichever is empty/NULL — a partial extraction (only some of
    the three parsed) still contributes what it has, never blocked on the
    others being present. "" when none are populated."""
    return "; ".join(p for p in (
        (row.get("architecture_lock") or "").strip(),
        (row.get("lighting_time_weather_lock") or "").strip(),
        (row.get("palette_lock") or "").strip(),
    ) if p)


def _find_canonical(envs: Optional[list], name: str, field_getter) -> str:
    """Shared whole-word LOCSET/env-name matcher (D6-6e): the approved
    environment's normalized name must appear as a whole, space-bounded
    phrase within the (normalized) candidate name, not be identical to it.
    `field_getter(env_row) -> str` extracts whichever field the caller
    wants (material_map, or the joined locks via env_locks_text)."""
    padded = f" {norm_env_name(name)} "
    for e in (envs or []):
        n = norm_env_name(e.get("name") or "")
        if n and f" {n} " in padded:
            return field_getter(e)
    return ""


def _canonical_line(envs: Optional[list], location_sets: Optional[dict],
                    matched_env: Optional[dict], field_getter, *, mode: str = "sheet") -> str:
    """Shared single-vs-multi-location precedence shape both material_line
    and environment_locks_line follow identically — see module docstring."""
    _check_mode(mode)
    if location_sets:
        parts = []
        for loc in location_sets:
            val = _find_canonical(envs, loc, field_getter)
            if val:
                parts.append(f"{loc.upper()}: {val}")
        return " ".join(parts)
    if matched_env:
        return field_getter(matched_env)
    return ""


def canonical_material_line(envs: Optional[list], location_sets: Optional[dict],
                            matched_env: Optional[dict], *, mode: str = "sheet") -> str:
    """D6-1/D6-1c (L20 — MATERIAL MAP): the CODE-RENDERED, canonical material
    map, sourced from video_environments.material_map (migration 142) —
    WINS over the planner LLM's own [MATERIAL | ...] line whenever a
    canonical entry exists, never a paraphrase of it. Returns "" (never
    invents) when no canonical entry exists anywhere relevant, so the
    caller's own parse_material_map(...) fallback fires unchanged.

    Multi-location scene (location_sets non-empty): one verbatim clause per
    LOCSET name that has a matching approved environment carrying a
    material_map — a location with no canonical entry is simply omitted
    (KNOWN GAP, see module docstring).

    Single-location scene (location_sets empty): matched_env's own
    material_map, or "" if it has none or nothing matched.

    D6-6e whole-word LOCSET matching applies (see module docstring).

    mode: "sheet" (once-per-block, assembler A) or "frame" (per-shot tail,
    assembler B) — accepted for callsite documentation; does not change the
    return value today (see module docstring)."""
    return _canonical_line(envs, location_sets, matched_env,
                           lambda e: (e.get("material_map") or "").strip(), mode=mode)


def canonical_environment_locks_line(envs: Optional[list], location_sets: Optional[dict],
                                     matched_env: Optional[dict], *, mode: str = "sheet") -> str:
    """D9-3/D9-3b (Custom Film EnvironmentLock harvest, migration 152): the
    CODE-RENDERED, canonical environment-locks clause, sourced from
    video_environments.architecture_lock / lighting_time_weather_lock /
    palette_lock — same precedence shape as canonical_material_line, one
    clause over. Returns "" when no canonical lock text exists anywhere
    relevant. Unlike material_map there is no planner-LLM equivalent line
    to fall back to (no [LOCKS | ...] directive tag exists), so "" simply
    omits the ENVIRONMENT LOCKS block entirely — byte-identical to every
    video before migration 152 and every video whose environments haven't
    been re-approved since (locks NULL).

    Multi-location scene: one verbatim clause per LOCSET name with a
    matching approved environment carrying locks populated — same KNOWN GAP
    as canonical_material_line (a location with no canonical locks is
    simply omitted).

    Single-location scene: matched_env's joined locks (env_locks_text), or
    "" if none.

    D6-6e whole-word LOCSET matching applies (see module docstring).

    mode: see canonical_material_line — accepted, does not change the
    return value today."""
    return _canonical_line(envs, location_sets, matched_env, env_locks_text, mode=mode)
