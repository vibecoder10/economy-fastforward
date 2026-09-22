# D5: Frame Arbiter + Learning Ratchet — Mission Plan (DRAFT, not executed)

Recon worker output. Written for the orchestrator to review, cut, and hand to
Sonnet builders. No product code touched. One overlap to respect:
`skills/video-pipeline/storyboard/coverage.py` is being edited live by another
worker (facing law) — this plan reads it for the axis-contract format but
does not touch it.

## Mission goal, in Ryan's terms

Right now, a bad frame either ships silently or gets caught by a human
scrolling through Review. Build a judge that looks at every new frame right
after it's drawn, and only spends money fixing it when the fix is likely to
work. The key part isn't the judge — it's that the judge has to **remember**.
If the same mistake shows up twice, stop paying to redraw it and instead
write down why it keeps happening, so a human (or the upstream prompt) fixes
the root cause. Never let auto-repair become an unbounded spend loop.

## Definition of Complete (verify each, don't assume)

1. A scene's frame batch landing in `coverage_to_app.store_scene()` triggers
   exactly one Frame Arbiter pass on at least one real prod scene, behind a
   flag — proven by a `generation_ledger` row (new `frame_qa` stage) and a
   matching Review-feed entry for that scene.
2. Every finding is classified MODEL_DEFECT / AUTHORING_DEFECT /
   TASTE_QUESTION, and only MODEL_DEFECT ever triggers `redraw_shot` —
   proven by one live AUTHORING_DEFECT and one live TASTE_QUESTION case
   where no redraw fires.
3. QA spend is hard-capped at $0.25/scene and $0.50/video, enforced
   **before** the call (not audited after) — proven by a unit test where a
   cap-exceeding call never fires, plus one live scene's ledger total.
4. The same fingerprint (rule id + stage + failure class) firing twice
   freezes auto-repair for that class and files a root-cause finding instead
   of a third redraw — proven by a scripted repeat-failure test.
5. A Ryan ruling entered via `upsert_quality_rule` reaches the prompt + gate
   + repair in the same commit (contract-triangle law) — proven by tracing
   one real ruling end to end.
6. The Review feed shows frame + reason + cost + fingerprint per finding;
   TASTE_QUESTION cards require a manual tap and are never auto-acted —
   proven by walking the feed in the browser (run-it-like-a-user).
7. `skills/video-pipeline/storyboard/coverage.py` has zero diff from this
   mission — proven by `git diff` at handoff.

## Learning-ratchet mechanics (law)

- **Fingerprint** = `(rule_id or failure_class, stage, failure_class)`.
  Computed the same way every time — no free text in the key.
- **First occurrence**: classify, act (repair/file/card) per the three
  buckets above, write the fingerprint row.
- **Second occurrence, same fingerprint**: auto-repair is FROZEN for that
  class. File a root-cause finding instead of spending a third redraw.
  Precedent: the motion-prompt gate already freezes on a 2-strikes basis
  (`motion_gate_status='blocked'` after the original write + one corrective
  retry, `backend/migrations/118_motion_gate_status.sql`) — but that freezes
  one SHOT, not a CLASS across scenes/videos. The ratchet needs a new table
  (or a `quality_rules` extension with `source='arbiter_learned'`), not a
  copy of `motion_gate_status`.
- **Ryan's ruling**: enters through `upsert_quality_rule` (already MCP-wired,
  `backend/routes/mcp.py`, backed by `backend/quality_rules.py`'s
  `create_rule` — upserts on `(tenant_id, rule_id)` conflict). Must land as
  prompt fix + gate + repair rule in the SAME commit (contract-triangle law,
  already established practice — don't invent a second wiring path).
- **Escalation, not just freeze**: if a rule still fires after its upstream
  fix is wired, that's worse than a fresh unseen failure — track a
  per-rule violation count over time and escalate (louder finding / higher
  priority) rather than re-freezing silently.
- **Success metric**: per-class spend trending to zero, read straight off
  `generation_ledger` grouped by the new `frame_qa` stage's fingerprint tag.

## Chunk list (parallel-first; edges only where output is consumed)

- **A1** (S) [D] — Arbiter budget guard. New `generation_ledger` stage
  (`frame_qa`), plus a `budget_refusal`-shaped pre-call cap check enforcing
  $0.25/scene + $0.50/video. $0 to build; verify with a unit test. No deps.
- **A2** (S) [D] — Fingerprint/classification schema. New table (or
  `quality_rules` extension) storing fingerprint, stage, failure_class,
  violation_count, frozen flag; upsert helper mirroring `create_rule`'s
  `ON CONFLICT` pattern. $0 to build. No deps (parallel with A1).
- **A3** (S) [D][V] — Frame Arbiter judge call. One vision call per new
  frame: prompt-obedience + `quality_rules` rubric, reusing
  `static_docu.py`'s self-fetch→base64→Sonnet pattern
  (`_download_image_b64`, `_vision_confirms`). Real paid verification on one
  scene — cost is UNKNOWN (see risk #1 below). Depends on A1 (cap must exist
  before first paid call), A2 (needs somewhere to write the fingerprint).
- **A4** (S) [D] — Neighbor-frame continuity check (axis/facing/style drift
  across a scene's frame set), folded into A3's judge call. READS
  `coverage.py`'s `parse_axis_line`/axis-contract format to judge against;
  does not edit it. Sequence after the in-flight facing-law worker lands, so
  it judges against the current contract, not a stale one. Depends on A3.
- **A5** (S) [D] — Auto-repair wiring. MODEL_DEFECT → `redraw_shot`
  (cheapest paid verb, $0.05/GPT-Image-2-2K) up to the per-scene cap;
  AUTHORING_DEFECT → zero redraws, file only; checks A2's frozen flag before
  any repair. Depends on A1, A2, A3.
- **A6** (H) [B] — Flag-gated single-scene prod deploy. Wire A1–A5 behind a
  flag scoped to ONE scene of ONE test video; deploy; run it live once;
  read back the actual ledger spend and confirm a repeat-fingerprint
  freezes. First real-dollar checkpoint — cheapest-first, before any UI.
  Depends on A1–A5.
- **A7** (S) [U] — Review feed. Extend the EXISTING
  `frontend/src/app/review/page.tsx` (already tab-based: scripts /
  storyboards / thumbnails / images, backed by `getPendingReview`) with a
  findings tab — frame, reason, class, cost, fingerprint, freeze state.
  TASTE_QUESTION renders as a decision card, never auto-acted. Schema-driven
  off A2, can start once A2 is fixed; needs A6's real data to sanity-check
  shape before calling it done. Depends on A2; verify against A6.
- **A8** (H) [D] — Ruling wire-up. `upsert_quality_rule` rulings flow into
  prompt + gate + repair in one commit; per-rule violation-count escalation
  once a rule is wired upstream but still fires. Depends on A2, A7.
- **A9** (H) [D] — Rollout beyond one scene. Only after A6 proves clean:
  widen the flag to all scenes / all tenants. This is where real
  spend-trending-to-zero data starts accumulating. Depends on A6, A8.

## Coverage.py overlap (explicit)

`skills/video-pipeline/storyboard/coverage.py` (2361 lines) owns the
AXIS-contract / facing-law logic at PROMPT-WRITING time
(`parse_axis_line`, `_facing_family`, `_reaction_pair`) — an in-flight
worker is editing it right now for the facing law. A4's neighbor-continuity
check judges the SAME concept (screen direction / facing) but AFTER the
pixels exist, downstream. Risk: the two efforts drift on vocabulary, or A4
gets built against a contract shape that changes under it mid-mission.
Mitigation already baked into A4 above: read-only dependency on coverage.py,
sequenced after the facing-law worker's change lands, never edited by this
mission (DoC #7 makes that a hard verify, not a promise).

## Riskiest assumptions + cheapest kill-check

1. **Vision-judge cost is cheap enough for a $0.25/scene cap to be usable.**
   UNVERIFIED — no `VISION_PRICE` constant exists anywhere in
   `skills/video-pipeline/shared/channel_profile.py`'s pricing block (image/
   voice/sound/script are all priced there; vision judgment calls are not,
   confirmed by grep). The static-docu arbiter has been calling Sonnet
   vision live in prod (see below) but nothing in the repo ledgers what that
   actually costs per call. Cheapest kill-check: make ONE real
   `_arbiter_confirms_render`-shaped call against a live scene as a $0 spike
   (before building A1's cap number) and read the real Anthropic usage for
   it — don't guess a per-call price from general model pricing knowledge.

2. ~~The static-docu arbiter is dead code with no production mileage~~ —
   CHECKED, not a risk. `se db` on prod: 1 tenant has
   `production_style_id='photo_documentary'`, and it has 8 `render_mode=
   'static_docu'` videos, all created in the last 30 days. The memory note
   calling this arbiter "committed NOT deployed" is STALE — it is live and
   has real recent mileage. This is good news for A3 (the base pattern is
   proven under load), but it also means A3 should study those 8 videos'
   actual `[qa: arbiter-approved after double reject]` stamps and
   `qa_rejected` park rate before assuming the pattern generalizes to
   coverage/storyboard batches, which are a different shape (many frames per
   scene vs. 1–3 reference-locked views per segment).
