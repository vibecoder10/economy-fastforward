# DVSU research-to-script compiler — deployed and health verified

The script writer now receives one machine’s deterministically selected supported facts, exact source quotes, a compact episode outline, and that machine’s saved wording reference. It no longer receives every machine’s full research archive. All original research stays saved.

## What changed
- Reuse the existing assessed claim ledger; select at most8 facts by fixed category/authority/ID rules. Record excluded claims and skip whole facts that cannot fit; never cut source quotes.
- Require fact IDs for each narration sentence. Code attaches authoritative citations, and the independent referee checks the sentence against those facts and source evidence.
- Bound packets at32,000 UTF8 bytes. Before writer/referee calls, enforce a conservative48,000 input-token upper bound (UTF8 bytes plus1,024 framing allowance), reserving output within the200,000 context ceiling. This is not an exact tokenizer count.
- Serialize repeated referee citations once, with lossless references. Keep alternate source context and existing factual checks.
- Reuse accepted narration for matching source/rules/model/outline fingerprints. Promote saved passed previews without another model call and resume failed current drafts before older stale ones.

## Verification
- **94 focused offline tests passed**, zero failures. Baseline had75 passing tests;19 added compiler/integration tests cover the new behavior.
- **20/20 real saved submarine research cards compiled**, identically on repeat. Every selected evidence reference resolved to its machine’s eligible source package; input snapshot hash remained unchanged.
- Old full-roster compact briefings: **768,782 bytes** per request attachment. New largest machine packet: **31,554 bytes**, median **14,707.5 bytes**. This is approximately96% less attached data even for the largest packet; it is not a measured token/cost saving.
- Largest writer conservative token bound: **33,861**. Largest reviewer bound using normalized saved research prose: **39,466**. Both below48,000;0 overflow cases in20-card replay.
- **No paid provider calls, script generation, voice, rendering, or upload.** Authorized backend deployment completed at22:32:37UTC.

## Delivery and limits
Six source/test files are integrated in the canonical StoryEngine checkout, byte-identical to the tested worktree. Release `64ddf60de` is committed, pushed, and deployed. Backend and worker are active on the same release; public API is healthy; homepage returns200; drain is normal and the deploy lock is clear. See [deployment.json](deployment.json). Existing unrelated changes were preserved. Prepared patch: [release.patch](release.patch); verification: [review.json](review.json), [final-tests.log](final-tests.log), [replay.json](replay.json), [integration.json](integration.json).

The replay proves compilation and request sizing, not live narration quality. Fresh model wording is not deterministic; accepted saved sections are reused deterministically. Research/UI schema and raw evidence remain intact. The ordered scene assembly and existing tenant/cancellation/spend guards remain in place.

Always next: quote and authorize one representative script-only canary before any full-episode rerun. Deployment is complete; fresh narration has not been generated. Audience/market checkpoint: DVSU editor reviews that section’s facts, exclusions, readability and manual repair count through the existing private workflow.
