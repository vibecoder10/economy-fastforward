"""Tests for scripts/seed_dvsu_quality_rules.py (checklist C46c).

Pure/local only: exercises the doc-parsing + section-based scope assignment
against the REAL storyengine/notes/dvsu-quality-law.md (the same doc Ryan
will actually seed from), and the boundary logic of _dvsu_applies_to(). Never
touches the DB — the script's own DB path (tenant resolution + the actual
write) is deliberately gated behind --apply and is NOT exercised here; this
chunk explicitly does not seed the live tenant.
"""

import importlib.util
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND))

import quality_rules as qr  # noqa: E402

_SEED_SCRIPT_PATH = _BACKEND / "scripts" / "seed_dvsu_quality_rules.py"
_DOC_PATH = _BACKEND.parent / "notes" / "dvsu-quality-law.md"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_dvsu_quality_rules", _SEED_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _load_seed_module()


def test_applies_to_boundaries_match_the_docs_section_ranges():
    assert seed._dvsu_applies_to("QL-1") == {"story": True}
    assert seed._dvsu_applies_to("QL-20") == {"story": True}
    assert seed._dvsu_applies_to("QL-21") == {"all": True}
    assert seed._dvsu_applies_to("QL-24") == {"all": True}
    assert seed._dvsu_applies_to("QL-25") == {"research": True}
    assert seed._dvsu_applies_to("QL-45") == {"research": True}
    assert seed._dvsu_applies_to("QL-46") == {"story": True}
    assert seed._dvsu_applies_to("QL-74") == {"story": True}


def test_applies_to_unrecognized_id_shape_fails_safe_to_all():
    assert seed._dvsu_applies_to("WEIRD") == {"all": True}
    assert seed._dvsu_applies_to("QL-999") == {"all": True}


def test_real_doc_parses_to_exactly_74_rules_ql1_through_ql74():
    text = _DOC_PATH.read_text()
    rows = qr.parse_markdown_table(text)
    ids = [r["rule_id"] for r in rows]
    assert len(rows) == 74
    assert ids == [f"QL-{n}" for n in range(1, 75)]


def test_real_doc_scope_counts_match_section_boundaries():
    text = _DOC_PATH.read_text()
    rows = qr.parse_markdown_table(text)
    by_scope = {}
    for row in rows:
        applies_to = seed._dvsu_applies_to(row["rule_id"])
        label = seed._scope_label(applies_to)
        by_scope[label] = by_scope.get(label, 0) + 1
    assert by_scope == {"story": 49, "research": 21, "all": 4}


def test_real_doc_known_severities_survive_parse_and_scope_assignment():
    text = _DOC_PATH.read_text()
    rows = qr.parse_markdown_table(text)
    by_id = {r["rule_id"]: r for r in rows}
    assert by_id["QL-1"]["severity"] == "hard_gate"   # word floor
    assert by_id["QL-3"]["severity"] == "hard_gate"   # twist-or-substitute gate
    assert by_id["QL-4"]["severity"] == "guidance"    # twist taxonomy
    assert by_id["QL-12"]["severity"] == "hard_gate"  # banned hype list
    assert "QL-12" in by_id and "Ban thumbnail-hype adjectives" in by_id["QL-12"]["law"]


def test_dry_run_never_imports_a_db_call_path(monkeypatch, capsys):
    """The default (no --apply) path must never touch the DB — no tenant
    resolution, no write. Proven by making both explode if reached."""
    import asyncio

    async def boom(*_a, **_k):
        raise AssertionError("dry-run must never touch the DB")

    monkeypatch.setattr(seed, "_resolve_tenant_id", boom)

    args = seed.argparse.Namespace(
        tenant_id="00000000-0000-0000-0000-000000000000",
        channel_name=None,
        doc_path=str(_DOC_PATH),
        apply=False,
    )
    exit_code = asyncio.run(seed.run(args))
    assert exit_code == 0
    out = capsys.readouterr().out
    # checklist C46e (OR-5 ruled): run() now appends the 2 hand-authored
    # Most Hated mode rows (QL-7-MH, QL-9-MH) on top of the doc's 74.
    assert "Parsed 76 law(s)" in out
    assert "dry-run" in out


# ---------------------------------------------------------------------------
# checklist C46e (OR-5 ruled) — the hand-authored "Most Hated" mode rows.
# ---------------------------------------------------------------------------

def test_most_hated_mode_rows_are_scoped_to_dvsu_mode():
    ids = {r["rule_id"] for r in seed._MOST_HATED_MODE_ROWS}
    assert ids == {"QL-7-MH", "QL-9-MH"}
    for row in seed._MOST_HATED_MODE_ROWS:
        assert row["applies_to"] == {"dvsu_mode": "most_hated"}


def test_most_hated_mode_rows_resolve_via_quality_rules_overrides():
    """The seeded law text must actually parse via quality_rules.
    resolve_dvsu_overrides — proves the seed script and the resolver's
    regexes agree on the exact wording, not just that both exist."""
    by_id = {r["rule_id"]: r for r in seed._MOST_HATED_MODE_ROWS}
    overrides = qr.resolve_dvsu_overrides(list(seed._MOST_HATED_MODE_ROWS))
    assert overrides["opener_budget"] == {"value": 0.2, "severity": by_id["QL-7-MH"]["severity"]}
    assert overrides["memorable_source"] == {"value": "crew_testimony", "severity": by_id["QL-9-MH"]["severity"]}


def test_scope_label_reports_dvsu_mode_value():
    assert seed._scope_label({"dvsu_mode": "most_hated"}) == "dvsu_mode=most_hated"


def test_dry_run_reports_most_hated_scope_bucket(capsys):
    """The dry-run summary must show the new dvsu_mode bucket, not silently
    fold it into "unscoped" or drop it from the printed breakdown."""
    import asyncio

    args = seed.argparse.Namespace(
        tenant_id="00000000-0000-0000-0000-000000000000",
        channel_name=None,
        doc_path=str(_DOC_PATH),
        apply=False,
    )
    asyncio.run(seed.run(args))
    out = capsys.readouterr().out
    assert "dvsu_mode=most_hated: 2 rule(s)" in out
