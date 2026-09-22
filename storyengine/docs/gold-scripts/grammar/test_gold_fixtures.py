"""Validates dvsu_grammar_check.check() against all 14 gold scripts.

Two passes per script:
1. The clean fixture paragraphs (fixtures.json) - proves check() doesn't false-flag
   real narration and characterizes how often the gold corpus itself misses the
   target bands (expected: some warnings, per script_grammar.json's empirical
   notes; zero forbidden-pattern violations - those are hard "never do this").
2. The raw .txt file (docs/gold-scripts/scripts/*.txt) for the 6 scripts that carry
   a leaked title/tail - proves the leakage detector fires exactly on those 6 and
   not on the other 8.

Run: python3 test_gold_fixtures.py
"""
import json
from pathlib import Path

from dvsu_grammar_check import check

GRAMMAR_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = GRAMMAR_DIR.parents[0] / "scripts"

EXPECTED_LEAKY = {
    "every-british-aircraft-carrier-class-ever-built.txt",
    "every-us-aircraft-carrier-ever-built.txt",
    "every-us-destroyer-class-ever-built-1898-1945.txt",
    "every-us-military-helicopter-ever-built.txt",
    "every-us-strategic-bomber-ever-built.txt",
    "most-hated-warships-by-their-own-crews-ever.txt",
}


def main() -> None:
    fixtures = json.loads((GRAMMAR_DIR / "fixtures.json").read_text(encoding="utf-8"))

    print("=" * 100)
    print("PASS 1: clean fixtures (narration only)")
    print("=" * 100)
    total_by_severity = {"violation": 0, "warning": 0, "info": 0}
    forbidden_violations = []  # hard-gate forbidden-pattern hits only (warnings are documented/expected)
    for f in fixtures:
        text = "\n".join(f["paragraphs"])
        violations = check(text)
        by_sev = {"violation": 0, "warning": 0, "info": 0}
        for v in violations:
            by_sev[v["severity"]] += 1
            total_by_severity[v["severity"]] += 1
            if v["rule"].startswith("forbidden_pattern") and v["severity"] == "violation":
                forbidden_violations.append((f["name"], v))
        print(f"{f['name'][:50]:50s} n={f['paragraph_count']:2d}  "
              f"violations={by_sev['violation']:2d} warnings={by_sev['warning']:2d} info={by_sev['info']:2d}")

    print()
    print("Totals across all 14 gold scripts:", total_by_severity)
    print()
    assert not forbidden_violations, f"hard-gate forbidden-pattern hits on gold scripts (should be 0): {forbidden_violations}"
    print("OK: zero hard-gate forbidden-pattern hits on any gold script "
          "(warning-level hits, e.g. 'legendary'/'revolutionary' usage, are documented in script_grammar.json).")

    # A leaked-content violation should never appear against the clean fixtures.
    leak_false_positives = [
        (f["name"], v)
        for f in fixtures
        for v in check("\n".join(f["paragraphs"]))
        if v["rule"] == "leaked_structural_content"
    ]
    assert not leak_false_positives, f"clean fixtures falsely flagged as leaky: {leak_false_positives}"
    print("OK: zero leaked_structural_content false positives on clean fixtures.")

    print()
    print("=" * 100)
    print("PASS 2: raw .txt files - leakage detector must fire on exactly the 6 known-leaky files")
    print("=" * 100)
    detected_leaky = set()
    for f in fixtures:
        raw = (SCRIPTS_DIR / f["name"]).read_text(encoding="utf-8")
        violations = check(raw)
        leaked = any(v["rule"] == "leaked_structural_content" for v in violations)
        marker = "LEAKY" if leaked else "clean"
        print(f"{f['name'][:50]:50s} detected={marker}")
        if leaked:
            detected_leaky.add(f["name"])

    assert detected_leaky == EXPECTED_LEAKY, (
        f"leak detection mismatch.\n missing: {EXPECTED_LEAKY - detected_leaky}\n"
        f" extra: {detected_leaky - EXPECTED_LEAKY}"
    )
    print()
    print(f"OK: leakage detector matched exactly the {len(EXPECTED_LEAKY)} expected files.")


if __name__ == "__main__":
    main()
