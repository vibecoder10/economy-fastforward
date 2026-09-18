# Holland automatic-evidence status

## Final bounded Holland verification — 2026-09-17

The deployed backend editorial-sufficiency contract is technically and content-review verified for one Holland-only preview. The actual frontend API wrapper made one paid POST, returned HTTP 200 in 27.8 seconds, and produced a 96-word, five-sentence paragraph with a seven-word verdict. It passed factual review, all six editorial checks, and all five ordered support-audit rows with no warnings. The separate wrapper-recovery receipt independently proves one paid POST followed by a 504 and three transient 502 GETs can recover the saved result without a second paid POST.

Backend release `7af5ab8ff` is live; the already-deployed frontend remains `6a590ed4` with its public asset proof. Validation includes 101 backend tests, 11 frontend tests, TypeScript and production-build receipts. The compact brief is 176 fact words / 2,200 canonical JSON bytes; the writer's conservative input upper bound is 5,987, not measured token usage. Fresh database readback records that only `research_payload.machine_script_previews.SS1` changed; the 20-entry roster, raw-source packages, production status, cost, script hash, and validation hash stayed unchanged.

This is bounded feature proof, not a full 20-machine roster-script completion, production promotion, publication, or Ryan's creative acceptance. Ryan's creative/listening acceptance remains pending. Evidence: [final scope audit](scope-audit-final.json), [actual editorial wrapper response](canary-ui-editorial-response.json), [editorial-sufficiency deployment](deployment-editorial-sufficiency.json), [production readback](production-readback-editorial-sufficiency.txt), [backend test receipt](tests-editorial-sufficiency.log), and [gateway recovery test receipt](tests-gateway-recovery.log).

## Historical pre-release state

The automatic source-to-brief path is verified locally, while the restored channel-writing contract is **not deployed**. The exact nine-file backend union now passes 100 checks with one dependency warning. The compact brief measures 176 fact words and 2,200 canonical JSON bytes. The completed research remains current; `PROMPT_RULES_VERSION = 4` invalidates only prior compiled previews.

The prior 110-word Holland preview was factual-passing by automation, but it is not creative acceptance. Its ending is a commissioning/licensing inventory recap, and Ryan’s earlier rejection of the 103-word preview for invented motive, patrol contrast, and geographic effect remains controlling.

## Restored writing contract and remaining gate

The local writer now targets 95–105 spoken words inside the approved 80–110 hard range, with approximately five sentences: original problem/proposed role, engineering choice, documented use, supported consequence, then a distinct paragraph-derived verdict of 18 words or fewer. The prompt permits a sourced lineage/training/used-as-designed substitute when no reversal is supported, limits specs to two useful details, and bans recap, new facts, and unsupported causation. The factual/editorial reviewer requires the same short, distinct conclusion, while the compiled mechanical check rejects an overlong final mapped sentence before any provider request.

At this earlier point, no new paid preview had run. The final verification described here was subsequently completed and is recorded above; Ryan’s creative/listening acceptance remains pending. This report does not claim publication or production promotion.

## Evidence

- [Source/brief plan and writing-contract acceptance](PLAN.md)
- [100-check backend union](tests-channel-contract.log)
- [Previous 110-word automated preview state](scope-audit.json)
- [Prior automated-passing 103-word preview](canary-preview_verified-response.json)
- [Gateway recovery plan](PLAN.md#gateway-completion-recovery)
