# Image selection: identity evidence and useful views

Status: implemented and deployed as d0ebcc97 at23:23UTC, with focused evidence isolation/search-context repair659f0345 at23:29UTC on 2026-09-15. Representative live comparison is in progress. Audit baseline:57d6a829. This extends IMAGE-GATHER-PLAN.md; CHECKLIST.md owns current state.

## What the previous implementation did (57d6a829)

- Finds Wikipedia lead/article photographs and Wikimedia Commons search results. Candidate identity trust comes from article/title matching or designation tokens in the filename, not a stored canonical image of each machine.
- Attempts one comparative vision ranking of at most six downloaded photographs. The prompt is aircraft-specific even for submarine entries. Unavailable/invalid ranking silently retains discovery order; existing worker logs show this fallback occurred, but do not preserve its cause.
- Hosts candidates in order and asks Claude to compare their pixels with the machine name, aliases, roster facts and filename. Saves the first passing candidate; previously cached photos bypass a fresh comparison.
- The model uses learned visual knowledge plus supplied text. It cannot reliably establish near-identical class membership from pixels alone. The current trust flag also overstates provenance in the prompt and discards source context.
- Missing-image messages discard the model's reason and conflate identity rejection with image/provider failures. Manual seeding expects an image URL; it does not extract an image from a Google search page. The host/download helpers do not validate that bytes really decode as an image.

Evidence: tasks/image-selection-source-map.md; backend/static_docu.py functions _gather_reference_candidates, _rank_reference_views, _vision_confirms, _prefetch_one_machine, seed_reference_from_url; tasks/image-gather-barracuda-miss.log. No claim is made that any specific rejected photograph was actually the wrong submarine.

## Astra selection decisions

1. Identity is an evidence gate, separate from photographic quality. Preserve the source page, caption, named subject, date/configuration and any documented class membership. Prefer attributable archive/manufacturer/museum records when available. A filename or an article containing the photo is a clue, not conclusive identification. Do not invent class membership or source evidence from visual familiarity.
2. Compare several distinct, adequately resolved candidates after establishing their identity evidence. Choose the most useful view among the inspected candidates; never claim the best image on the internet. Bound discovery and comparison, deduplicate repeated copies, and expose the count actually compared.
3. Score whole-subject coverage, visibility of defining features, sharpness/usable resolution, obstruction and perspective distortion. For submarines, favor a readable side or three-quarter view with bow, stern, hull profile and sail visible. Water, launch wrapping, cranes, foreground objects and severe foreshortening reduce usefulness. No single angle wins unconditionally: the clearest side view can beat a dramatic three-quarter view. Aircraft retain aircraft-specific criteria; other machines need their own relevant features.
4. Select one primary photo. Where one view hides essential geometry, retain a complementary source-backed view as supporting evidence; do not pretend one photograph reveals unseen parts. Limited archival coverage must be explained as a limitation.
5. Save the selected source and the comparison rationale, identity evidence, evaluated alternatives and limitations. The UI should distinguish identity checked from view comparison completed and show why this image was selected. Uncertain identity remains review-needed; a ranking outage cannot silently mean best-view selection succeeded.
6. Preserve structured rejection reasons: wrong identity/configuration, insufficient evidence, unsuitable view, invalid/non-image URL, download failure and vision-provider failure. A Google search-results page must get an actionable image-link message, not an assertion about the submarine's appearance.

## Next executable step: evidence capture before implementation

- Input/source: 57d6a829 candidate helpers and saved 20-entry submarine roster; Barbel as an existing obstructed-view example, Albacore as a prior miss; current image source metadata from public archive/Wikipedia/Commons responses.
- Action: collect a bounded candidate comparison fixture for those two entries, including exact source page/caption, original image URL, documented subject/class relationship and image dimensions. Parent reviews what the metadata can actually establish and defines precise implementation interfaces and regression fixtures from that evidence.
- Write boundary/output: tasks/image-selection-candidates.json and tasks/image-selection-review.md only; no cache, roster, source images, research or production mutations.
- Dependencies: this source audit and current saved roster readback. Terra may collect the specified evidence; Astra owns source interpretation, acceptance decisions and the implementation plan.
- Acceptance evidence: at least two distinct usable views where available, explicit missing evidence where unavailable, and a reproducible account of why the old ordering/verification was inadequate. No claim that source identity was independently verified unless the consulted source supports it.
- Authority/stop: read-only source collection and local fixtures authorized; no paid vision/generation, blanket re-gather, deployment or forced cache acceptance in this capture step. Stop and return unavailable source evidence; do not invent it. Implementation requires Astra's complete file/interface/test plan before Terra begins.

Market checkpoint: documentary creators need correct, clearly recognizable machine references. The existing submarine production is the real-world test: Ryan can inspect the selected view and its evidence before it is used downstream.
