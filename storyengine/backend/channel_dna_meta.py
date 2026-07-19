"""Provenance envelope for `channel_profiles.channel_identity` JSONB (C40).

Three different callers write into the SAME JSONB column today:
`identity_builder.build_channel_identity` (a from-scratch rebuild of the
voice/hook/structure/research/thumbnail fields from the channel's own top
videos), `channel_format.set_channel_format` (chat-driven visual_format /
format_locked edits), and `pipeline_executor._run_channel_formula_thumbnail`
(a best-effort thumbnail_blueprint cache). Before C40 each one read/wrote the
column its own way (one blind full overwrite, two different SQL `||` merges)
with no record of WHO set a field, WHEN, or what it replaced.

This module is the ONE place that mutates the JSONB from now on. It adds two
reserved, underscore-prefixed top-level keys inside the SAME object (no new
table, no migration — checklist C40 `[D]`):

  - `_sources`: {field_name: {"learner": str, "at": iso_ts, "confidence":
    float|None}} — stamped for every field a write actually touches.
  - `_history`: a list, oldest-first, capped at `HISTORY_LIMIT` entries, of
    {"at", "learner", "fields_changed": [...], "previous": {field: old_value}}
    snapshots — enough to show what changed and where it came from, and to
    restore a single field, without a second table.

Merge semantics (the whole point of this module): `stamp_identity_write`
read-modify-writes in PYTHON, not SQL. A caller fetches the CURRENT
`channel_identity` dict, calls this function with only the fields it's
changing, and gets back a full replacement dict where:
  - every field NOT passed in `fields` (including ones from a DIFFERENT
    writer, e.g. channel_format's `visual_format` surviving an
    identity_builder rebuild) is preserved byte-for-byte;
  - the envelope itself (`_sources`, `_history`) is preserved and extended,
    never clobbered;
  - a write can never smuggle new content INTO the envelope keys (a `fields`
    dict that happens to include "_sources" is ignored for that key).

Readers (identity.py, channel_format.get_channel_format, static_docu.py,
routes/chat.py's `_format_identity`, pipeline_executor's thumbnail/research
reads) all pluck specific known keys off the dict rather than iterating it,
so they already ignore the underscore keys structurally — see
tests/test_channel_dna_meta.py for the byte-identity proof pinning that.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any, Optional

SOURCES_KEY = "_sources"
HISTORY_KEY = "_history"
# C42 (P4.1c): the most recent channel_dna.learn_channel() orchestration
# report — {"at", "ok", "learners": {name: {status, summary, fields_written,
# error}}} — stashed here so a later chat turn ("show the channel digest")
# or the thin GET /api/channel-dna/status route can render the confirmable
# digest card without re-running any learner. Set via `stamp_last_run`
# (below), NOT through `stamp_identity_write`'s per-field loop — it's
# metadata about a RUN, not a channel-identity field, so it gets no
# `_sources` stamp and produces no `_history` entry of its own.
LAST_RUN_KEY = "_last_run"
ENVELOPE_KEYS = (SOURCES_KEY, HISTORY_KEY, LAST_RUN_KEY)

# How many _history snapshots to keep. Oldest dropped first.
HISTORY_LIMIT = 20

# Sentinel distinguishing "this field didn't exist before the write" from
# "the field existed and was explicitly None" in a restored/previous value.
_MISSING = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def coerce_identity(raw: Any) -> dict[str, Any]:
    """Normalize whatever `channel_profiles.channel_identity` comes back as
    (asyncpg returns JSONB with no codec registered, so it's often a raw JSON
    STRING — see identity.py's `_clean_frameworks` docstring for the same
    asyncpg quirk on a sibling column) into a plain dict. None/malformed/
    non-dict input -> {} ; never raises.
    """
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return copy.deepcopy(raw) if isinstance(raw, dict) else {}


def stamp_identity_write(
    identity: Optional[dict[str, Any]],
    fields: dict[str, Any],
    learner: str,
    confidence: Optional[float] = None,
) -> dict[str, Any]:
    """Merge `fields` on top of `identity`, stamping `_sources` provenance
    and appending one `_history` snapshot for whatever actually changed.

    Returns a NEW dict — never mutates the `identity` argument in place, so
    callers can safely diff before/after.

    - Fields not present in `fields` (and the envelope itself) survive
      untouched — this is a merge, not a replace.
    - Every key in `fields` gets a fresh `_sources[key]` stamp (learner, ISO
      timestamp, confidence), even when the value is unchanged — a
      re-confirmation from a learner is itself provenance worth recording.
    - A `_history` entry is appended only when at least one field's VALUE
      actually changed (`!=` comparison), so re-saving identical output
      doesn't spam history. `previous[field]` is `None` when the field did
      not exist before this write (there's nothing meaningful to restore to
      besides "absent" — `restore_field` treats that the same as any other
      stored value).
    - `_history` is capped at `HISTORY_LIMIT`, oldest dropped first.
    - Keys "_sources"/"_history" inside `fields` are ignored — a writer can
      never smuggle content into the envelope through the normal field path.
    """
    merged = coerce_identity(identity)
    sources = merged.get(SOURCES_KEY)
    sources = copy.deepcopy(sources) if isinstance(sources, dict) else {}
    history = merged.get(HISTORY_KEY)
    history = list(history) if isinstance(history, list) else []

    at = _now_iso()
    previous: dict[str, Any] = {}
    for key, value in (fields or {}).items():
        if key in ENVELOPE_KEYS:
            continue
        existed = key in merged
        old = merged.get(key)
        if (not existed) or old != value:
            previous[key] = old if existed else None
        merged[key] = value
        sources[key] = {"learner": learner, "at": at, "confidence": confidence}

    if previous:
        history.append({
            "at": at,
            "learner": learner,
            "fields_changed": sorted(previous.keys()),
            "previous": previous,
        })
        if len(history) > HISTORY_LIMIT:
            history = history[-HISTORY_LIMIT:]

    merged[SOURCES_KEY] = sources
    merged[HISTORY_KEY] = history
    return merged


def stamp_last_run(identity: Optional[dict[str, Any]], run_digest: dict[str, Any]) -> dict[str, Any]:
    """Set `_last_run` to `run_digest` (checklist C42). Returns a NEW dict —
    same non-mutating contract as `stamp_identity_write` — with every other
    key (including the `_sources`/`_history` envelope and every learned
    field) preserved byte-for-byte. Deliberately bypasses the per-field
    provenance loop: this is a run report, not a field a learner taught."""
    merged = coerce_identity(identity)
    merged[LAST_RUN_KEY] = run_digest
    return merged


def field_provenance(identity: Optional[dict[str, Any]], field: str) -> Optional[dict[str, Any]]:
    """{"learner", "at", "confidence"} for `field`, or None if it was never
    stamped (or `identity` carries no envelope at all)."""
    ci = coerce_identity(identity)
    sources = ci.get(SOURCES_KEY)
    if not isinstance(sources, dict):
        return None
    prov = sources.get(field)
    return dict(prov) if isinstance(prov, dict) else None


def restore_field(identity: Optional[dict[str, Any]], field: str, history_index: int) -> dict[str, Any]:
    """Undo `_history[history_index]`'s change to `field`: set it back to the
    value recorded in that entry's `previous[field]`. Returns a NEW identity
    dict — the restore is itself stamped as a fresh write (learner=
    "restore"), so it's provenance-tracked and can, in turn, be restored
    away.

    Raises ValueError if `history_index` is out of range or that history
    entry didn't change `field` (nothing to restore to).
    """
    ci = coerce_identity(identity)
    history = ci.get(HISTORY_KEY)
    if not isinstance(history, list) or not (0 <= history_index < len(history)):
        raise ValueError(f"history_index {history_index} out of range (0..{len(history or []) - 1})")
    entry = history[history_index]
    prev = entry.get("previous") if isinstance(entry, dict) else None
    if not isinstance(prev, dict) or field not in prev:
        raise ValueError(f"history entry {history_index} did not change field '{field}'")
    restored_value = prev[field]
    return stamp_identity_write(ci, {field: restored_value}, learner="restore", confidence=None)


def latest_history_index_for_field(identity: Optional[dict[str, Any]], field: str) -> Optional[int]:
    """The index of the most recent `_history` entry that changed `field`, or
    None if it's never changed (nothing to revert). Checklist C42's digest
    card uses this to decide whether to show a Revert button, and the revert
    op itself re-resolves the index THIS way at execute time rather than
    trusting a client-supplied index — the identity may have changed between
    when the card was rendered and when the button is tapped."""
    ci = coerce_identity(identity)
    history = ci.get(HISTORY_KEY)
    if not isinstance(history, list):
        return None
    for i in range(len(history) - 1, -1, -1):
        entry = history[i]
        if isinstance(entry, dict) and field in (entry.get("fields_changed") or []):
            return i
    return None
