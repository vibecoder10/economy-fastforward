# Machine research automation repair

Status: local implementation and review passed; not deployed. Live all-machine research, script, and full-video completion remain unproven.

## Intended flow

Locked machine name → normalized research subject → fetched source excerpts → model-written, citation-reviewed research summary → saved per-machine card → resume remaining roster → model-led script assembly using saved summaries and original evidence.

## Verified causes

The saved class display labels caused source filters to demand words such as “through” alongside the class name. Five saved source packages held useful class excerpts but failed that identity filter. Four other attempted packages had no fetched excerpts. The automation also counted only existing verdicts instead of the full locked roster, and needs_review could be recorded as completed. Research cards did not yet contain the readable summary that Ryan expected.

## Prepared changes

- Normalize naval range/class display names while retaining subject and variant checks. Permit one bounded alternate source-discovery wave when fetched evidence is empty.
- Generate and persist a readable research briefing with sources and claim citations per machine. Keep failed drafts available for review; invalidate summaries if subject or sources change.
- Resume the full locked roster, reuse current completed summaries, continue independent machines after known temporary connection failures, and stop on account/database/unknown failures. Require persisted current summaries before advancing.
- Feed saved briefings into model-led script writing as context; factual claims still cite original excerpts. This adds flexible model synthesis, not calibrated probability estimates or invented confidence scores.
- Display summaries and source links in Research; expose incomplete research as an actionable failure.

## Review evidence

Three bounded Terra workers executed Astra-authored packages. A/B rounds 1–3 corrected identity punctuation, receipt recording, checkpoint refusal, and stale-summary diagnostics. C/D covered orchestration and display. Astra integration review repaired one legacy test fixture that incorrectly entered unrelated image checks.

126 combined backend tests passed against Git baseline f92c863b550dcf5cd3a72e351d045b554ef8fdcf with only the scoped backend changes overlaid. Frontend production build passed per D receipt. git diff --check passed. Tests mocked provider/database operations; no paid generation was performed. UI conditional rendering was reviewed; browser visual acceptance is outstanding.

Saved-source replay recovered candidate eligibility for Gato, Balao, Tang, Barbel and Albacore without provider calls. This is an eligibility result, not live summary generation or independent historical verification. Empty source packages still require actual alternate retrieval.

## Next action and limits

Approve deployment under CLAUDE.md's live-system rule; verify the changed UI before release, deploy only release.patch scope through scripts/se.sh, and verify service health. Then authorize a paid, research-and-script-only canary on the existing video, preserving roster/images/completed work. Do not start voice, images, clips, rendering, or upload as part of that canary. Record exact saved summary counts, script state, unresolved machines, and provider usage. End-to-end video remains a separate open acceptance check.

Unrelated representative-roster work and research-agent changes are excluded from release.patch. Recheck concurrent workspace and production state before release.
