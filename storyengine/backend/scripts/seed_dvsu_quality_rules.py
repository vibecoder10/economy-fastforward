#!/usr/bin/env python3
"""Seed the DvsU tenant's quality_rules table from storyengine/notes/
dvsu-quality-law.md (checklist C46c — DvsU deltas as the reference
implementation).

This is a deliberate, by-name script — NOT wired into any migration, cron,
or auto-seed path. The sandbox DB is the LIVE production database and DvsU
is a real paying/production tenant, so this only ever runs when a human (or
the orchestrator, on Ryan's explicit instruction) invokes it by name.

WHAT IT DOES
    1. Parses storyengine/notes/dvsu-quality-law.md's QL-1..QL-74 pipe-table
       rows via quality_rules.parse_markdown_table (the same deterministic,
       no-LLM parser C46b shipped and proved against this exact doc).
    2. Assigns each rule's applies_to SCOPE by the doc's own SECTION
       boundaries (not the generic keyword-heuristic default
       quality_rules.suggest_applies_to() proposes for an arbitrary
       uploaded doc) — see _dvsu_applies_to() below for the exact ranges
       and the reasoning per section.
    3. Writes via quality_rules.bulk_create_rules(source="seed"), which is
       IDEMPOTENT: re-running edits existing rows in place (ON CONFLICT
       (tenant_id, rule_id) DO UPDATE) rather than duplicating — safe to
       re-run after editing the doc.

USAGE
    # Dry run (default): parses + prints a scope-by-section summary, writes
    # nothing. Always run this first.
    python scripts/seed_dvsu_quality_rules.py --tenant-id <uuid>
    python scripts/seed_dvsu_quality_rules.py --channel-name "Designed vs"

    # Actually write the 74 rows (idempotent — safe to re-run):
    python scripts/seed_dvsu_quality_rules.py --tenant-id <uuid> --apply

Exactly one of --tenant-id / --channel-name is required. --channel-name
resolves via a case-insensitive substring match against
channel_profiles.channel_name; the script refuses to proceed (prints the
matches, exits nonzero) if that match isn't exactly one tenant, so an
ambiguous or wrong channel name can never silently seed the wrong tenant.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def load_env_file(path: Path) -> None:
    """Mirror encrypt_secrets.py / run_migrations_strict.py: pull env vars
    from a .env file without overriding anything already set."""
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# ---------------------------------------------------------------------------
# Section-based scope assignment — read from the doc's own structure, not
# guessed per-law. See storyengine/notes/dvsu-quality-law.md's section
# headers for the exact boundaries this mirrors:
#   Section 1 "SCRIPT LAWS" -> Writing craft (QL-1..15) + Mechanical/code-
#     enforced (QL-16..20): both gate the STORY PARAGRAPH the static_docu
#     harness assembles -> "story" scope (matches migration 105's own
#     comment: "QL-1..QL-15" under the "story" key, extended here through
#     QL-20 since the mechanical checks gate the identical paragraph).
#   Section 2 "PIPELINE LAWS":
#     Channel identity (QL-21..24) governs the whole video's premise
#       (subject/angle/controversy/audience) regardless of which stage is
#       running -> "all" scope.
#     Research and selection (QL-25..45) -> "research" scope.
#     Voiceover / Image / Thumbnail / Producer file (QL-46..74): downstream
#       static_docu production laws. quality_rules.py's applies_to
#       vocabulary has no dedicated voiceover/image/thumbnail scope key
#       today (only all/research/story/animated/realistic/channel_format —
#       see quality_rules.py's module docstring) — "story" is the closest
#       existing fit (all are part of the same static_docu pipeline). This
#       is a real vocabulary gap, not papered over: flagged in the C46c
#       report, not silently assumed correct.
# ---------------------------------------------------------------------------

def _dvsu_applies_to(rule_id: str) -> dict:
    try:
        n = int(rule_id.split("-", 1)[1])
    except (IndexError, ValueError):
        return {"all": True}
    if 1 <= n <= 20:
        return {"story": True}
    if 21 <= n <= 24:
        return {"all": True}
    if 25 <= n <= 45:
        return {"research": True}
    if 46 <= n <= 74:
        return {"story": True}
    return {"all": True}


def _scope_label(applies_to: dict) -> str:
    if applies_to.get("all"):
        return "all"
    if applies_to.get("research"):
        return "research"
    if applies_to.get("story"):
        return "story"
    return "unscoped"


async def _resolve_tenant_id(tenant_id: str | None, channel_name: str | None) -> str:
    from database import fetch_all, fetch_one

    if tenant_id:
        row = await fetch_one("SELECT id, name, slug FROM tenants WHERE id = $1", tenant_id)
        if not row:
            raise SystemExit(f"No tenant found with id={tenant_id!r}")
        print(f"Resolved tenant: {row['name']!r} (slug={row['slug']!r}, id={row['id']})")
        return str(row["id"])

    rows = await fetch_all(
        "SELECT t.id, t.name, t.slug, cp.channel_name "
        "FROM tenants t JOIN channel_profiles cp ON cp.tenant_id = t.id "
        "WHERE cp.channel_name ILIKE $1",
        f"%{channel_name}%",
    )
    if len(rows) != 1:
        print(f"--channel-name {channel_name!r} matched {len(rows)} tenant(s), need exactly 1:")
        for row in rows:
            print(f"  - tenant_id={row['id']}  channel_name={row['channel_name']!r}  slug={row['slug']!r}")
        raise SystemExit(1)
    row = rows[0]
    print(f"Resolved tenant: {row['channel_name']!r} (slug={row['slug']!r}, id={row['id']})")
    return str(row["id"])


async def run(args: argparse.Namespace) -> int:
    import quality_rules
    from database import close_pool

    doc_path = Path(args.doc_path) if args.doc_path else (BACKEND.parent / "notes" / "dvsu-quality-law.md")
    if not doc_path.exists():
        print(f"ERROR: doc not found at {doc_path}")
        return 1
    text = doc_path.read_text()

    parsed = quality_rules.parse_markdown_table(text)
    if not parsed:
        print(f"ERROR: parse_markdown_table found 0 rows in {doc_path} — doc format may have changed.")
        return 1

    rows = []
    by_scope: dict[str, int] = {}
    for row in parsed:
        applies_to = _dvsu_applies_to(row["rule_id"])
        rows.append({**row, "applies_to": applies_to})
        label = _scope_label(applies_to)
        by_scope[label] = by_scope.get(label, 0) + 1

    print(f"Parsed {len(rows)} law(s) from {doc_path.name}:")
    for label in ("story", "research", "all", "unscoped"):
        if label in by_scope:
            print(f"  {label:10s}: {by_scope[label]} rule(s)")
    severity_counts: dict[str, int] = {}
    for row in rows:
        severity_counts[row["severity"]] = severity_counts.get(row["severity"], 0) + 1
    print("Severity breakdown:", ", ".join(f"{k}={v}" for k, v in sorted(severity_counts.items())))

    if not args.apply:
        print("\n[dry-run] would upsert the above rows with source='seed'. Nothing written.")
        print("Re-run with --apply to write.")
        return 0

    tenant_id = await _resolve_tenant_id(args.tenant_id, args.channel_name)
    saved = await quality_rules.bulk_create_rules(tenant_id, rows, source="seed")
    print(f"\nUpserted {len(saved)} quality_rules row(s) for tenant {tenant_id} (source='seed').")
    await close_pool()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    tenant_group = ap.add_mutually_exclusive_group(required=True)
    tenant_group.add_argument("--tenant-id", help="DvsU's tenant UUID.")
    tenant_group.add_argument("--channel-name", help="Substring match against channel_profiles.channel_name.")
    ap.add_argument("--doc-path", help="Override the law-doc path (default: storyengine/notes/dvsu-quality-law.md).")
    ap.add_argument("--apply", action="store_true", help="Actually write rows. Default is dry-run (report only).")
    args = ap.parse_args()

    load_env_file(BACKEND.parent / ".env")
    load_env_file(BACKEND / ".env")

    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
