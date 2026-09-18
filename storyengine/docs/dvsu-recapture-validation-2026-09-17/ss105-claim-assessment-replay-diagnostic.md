# SS105 stored claim-assessment replay

The stored fenced JSON parses successfully into nine claims. Replaying it with `research_claim_assessment._eligible` and `_validated_claims`, with no model, network, or database access, rejects the full response at C2. C1 and C3–C9 each normalize when replayed alone.

| Claim | Individual replay | First failing field | Evidence result |
| --- | --- | --- | --- |
| C1 | pass | — | S1-E1, DVSU1-E1 exact |
| C2 | fail | `evidence[0].quote` | DVSU1-E1 mismatch; S1-E7 exact |
| C3 | pass | — | DVSU1-E1, S1-E8, S1-E10 exact |
| C4 | pass | — | DVSU1-E1 exact |
| C5 | pass | — | DVSU1-E1 exact |
| C6 | pass | — | DVSU1-E1 exact |
| C7 | pass | — | DVSU1-E1 exact |
| C8 | pass | — | S1-E1, DVSU1-E4 exact |
| C9 | pass | — | DVSU1-E1 exact |

The exact rejection is at [`research_claim_assessment.py`](/Users/ryanayler/AgentVault/Projects/story-engine/storyengine/backend/research_claim_assessment.py:74): `_source_quote_slice` cannot find C2's first raw quote in eligible candidate `DVSU1-E1`, causing the `_quote_rows` guard at line 75 and therefore `_validated_claims` at lines 100–105 to return `None`.

Raw C2 quote:

> in 1922, when she was modified to both bring her up to current standards with a larger deck gun and to fit her for experimental use as a base for a small scouting seaplane

Candidate `DVSU1-E1` contains:

> until 1922, when she was modified to both bring her up to current standards with a larger deck gun and to fit her for experimental use as a base for a small scouting seaplane

The missing word is `until`. This is not a curly-quote/dash/nonbreaking-space variant, so the limited typography fallback at lines 48–60 also rejects it. `DVSU1-E1` is otherwise eligible: source ID `DVSU1`, URL `https://www.ibiblio.org/hyperwar/OnlineLibrary/photos/sh-usn/usnsh-s/ss105.htm`, locator `DVSU1-E1; R1-E1; source=https://www.ibiblio.org/hyperwar/OnlineLibrary/photos/sh-usn/usnsh-s/ss105.htm`, and `identity_requires_review=false`.

No per-claim replay reached an identity review, class-context, missing-ID, or narrative-role failure. The full structured record is in [ss105-claim-assessment-replay-diagnostic.json](/Users/ryanayler/AgentVault/Projects/story-engine/storyengine/docs/dvsu-recapture-validation-2026-09-17/ss105-claim-assessment-replay-diagnostic.json).
