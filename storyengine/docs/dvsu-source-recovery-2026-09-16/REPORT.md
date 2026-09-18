# Source recovery repair — deployed

Release c5956e190 deployed at 2026-09-16 23:44:04 UTC via se.sh. Backend and worker match the release; source hashes match; API healthy, frontend200, normal drain, lock clear.

## Confirmed cause
The original Naval Undersea Museum page already had Holland’s training service. Baseline cc9ee724b flattened the page and retained only short name/hull windows: two excerpts, neither with training. The repair preserves publisher headings and admits the exact1152-character Holland section. Production-server free HTTP capture now returns three excerpts, including training. All excerpts are exact normalized source text. The same section survives actual fetch and source-package assembly in the regression test.

## Changes and verification
Named sections remain within3000characters and10excerpts, with wrong-hull/foreign-ship rejection and no cross-heading assembly. Existing non-named extraction remains unchanged. Factual search now tries the existing archive fallback when direct capture has no usable evidence; archive URLs must be returned as available/status200 by the availability API and match the requested source. TLS verification remains enabled. One-machine failures return the target machine’s warnings, not the last roster row.

38 source/identity/search tests passed;18 targeted tests passed with11 overlapping tests;12 additional factual tests passed. Six old factual cache-readiness tests fail identically on unmodified cc9ee724b (tests-baseline.log); these fixtures lack current complete brief evidence. No assertion or gate was weakened. Terra authored bounded regression tests; Astra reviewed and integrated round1.

## Limits and next action
Zero paid provider calls and no live data writes. Production script, validation, scene rows and research payload hashes are unchanged. Archive fallback contract tests pass, but live archive availability returned429 locally, so live archive recovery is not claimed. The recovered source explicitly supports design, training service and A-class successors; it does not explicitly establish intended operational mission. Existing assessed role labels still need review. No new assessment or finished DVSU script has passed this repair.

Always next: establish Holland’s intended role from an explicit primary source and review the four-field brief before any further paid preview. Do not rerun the full episode or claim script quality restored.
