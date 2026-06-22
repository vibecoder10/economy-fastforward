# GOAL - StoryEngine: slop is structurally impossible (good by construction)

**North star:** The engine cannot produce a video that carries a YouTube demonetization signal. Not "it warns you" - it *can't make one*. A creator never thinks about scripts being generic, thumbnails looking the same, or videos feeling mass-produced, because the architecture guarantees every output is custom, varied, and carries a real point of view. This is a core selling point of the cloneable engine: slop-proof by default.

**Success looks like:** A creator clicks generate 20 times for one channel and gets 20 videos a YouTube reviewer would see as clearly different - different angles, different hooks, different thumbnails, different look - with zero effort and zero worry from the creator. The engine simply never hands them a bad one.

**Status:** Plan drafted 2026-06-21, awaiting go. Research done (YouTube "inauthentic content" policy). Code audited and mapped.

**Decision on record (supersedes earlier draft):** **No user-facing blocks, warnings, or verdicts.** Safety is baked into generation. Any check is silent and internal - if a draft is too close to history or too generic, the engine auto-re-rolls it before proceeding. The creator never sees it.

**Honest caveat:** "Cannot" is the design target, not a legal guarantee - YouTube uses human review and fuzzy rules. We engineer out every known mass-production signal so the output sits firmly on the safe side. Numeric thresholds below are conservative internal guardrails, tunable from real data.

---

## The policy in one screen (what we engineer against)

YouTube didn't ban AI. On 2025-07-15 it renamed "repetitious content" to the **"inauthentic content"** policy and enforced it hard through 2026. Two rules:

1. **Reused content** - can't repackage existing material without adding real value.
2. **Inauthentic / mass-produced** - can't ship videos that look templated, interchangeable, or made-at-scale with no human point of view.

The line is **replacement vs. assistance**. YouTube's own test: "if the average viewer can clearly tell your videos differ from each other, you're fine."

**What we engineer in - two walls and one label, all automatic:**
- **Wall 1 - per-video originality:** every script structurally carries a genuine angle/opinion. Built in, not checked.
- **Wall 2 - a genuinely new PLOT every time:** the script generator is fed the channel's recent plots and required to tell a story that shares nothing essential with them. **The channel's look, format, and title style MAY stay consistent - that is its brand, and looking similar is fine.** Only the plot (story, events, arc) must differ. (Decision, Ryan 2026-06-21: "every video can look the same, it just needs a completely different plot from the last one.")
- **The label - disclosure:** if a video ever uses a realistic real person or a cloned real voice, the disclosure label is applied automatically and invisibly.

---

## Architecture: good by construction (no gates)

The mechanism is the same history-awareness, but it lives *inside* generation as a constraint, not after it as a judge.

1. **Deep per-channel identity (super custom).** Each channel gets a genuinely distinct creative fingerprint - voice, angle, structure, look - so its videos don't look like any other channel's (protects the cloneable engine from an account-level "same skeleton everywhere" signal).
2. **History-aware, plot-forced generation.** The script generator receives a compact record of the channel's recent PLOTS (the "fingerprint": title + a short plot summary) and is *required to tell a genuinely new story*. Look/format/title style may repeat (brand); only the plot is forced to differ. Repetition of plot is designed out at the prompt layer.
3. **Built-in point of view.** The script craft itself guarantees each video carries a real angle, opinion, or insight - never flat encyclopedia narration. This is Wall 1, structural.
4. **Silent self-correction.** Inside each generation step, a cheap internal check confirms the draft is far enough from history and not generic. If not, the engine re-rolls automatically (pushing parameters harder each retry), then proceeds. Invisible to the creator - never a warning, never a block.
5. **Automatic disclosure.** Detection + label application happen silently, only when actually warranted.

### DB changes (reuse existing columns where possible)
- New: `videos.slop_fingerprint` (JSONB) - the compact per-video record other generations diverge from.
- `videos.agent_paper_trail` (exists, JSONB) -> append internal self-check notes for OUR debugging only (not shown to creators).
- New: `videos.ai_disclosure_required` (BOOL default false), `videos.ai_disclosure_text` (TEXT) - auto-set, auto-applied.
- Track `title_formula_id` (which MF-x was used) per video - inside the fingerprint or its own column.
- (`videos.monetization_risk` exists but we will NOT surface it to creators; optional internal-only use.)

---

## Phase 0 - Foundations  `[core built + live-proven; migration/backfill pending apply]`
Goal: the plumbing diversity-forced generation needs. No behavior change yet.
- [x] Migration `backend/migrations/055_originality_engine.sql`: adds `slop_fingerprint` (JSONB), `ai_disclosure_required` (BOOL), `ai_disclosure_text` (TEXT); reuses existing `monetization_risk` + `agent_paper_trail`. WRITTEN, not yet applied (prod apply is gated).
- [x] New module `backend/originality.py`: `build_fingerprint(video)`, `load_recent_fingerprints(tenant_id, limit)`, `summarize_recent_for_prompt(...)` (the diversity block fed INTO generators), and `assess_draft(...) -> OriginalityVerdict` (the internal silent self-check; `.needs_reroll` is the re-roll signal). Direct `claude-sonnet-4-6` cloud call (NOT Kie). Fails open. LIVE-PROVEN 2026-06-21: templated near-dupe -> RED/needs_reroll, distinct opinionated draft -> GREEN.
- [ ] Backfill fingerprints for each tenant's existing videos (needs live DB — do on the VPS).
Done when: I can build a fingerprint and load a channel's recent history, and the internal check returns sane verdicts on real videos. Nothing surfaced to creators.  ✅ core DONE; backfill + migration-apply remain.

## Phase 1 - Plot-forced generation (the core)  `[script + title wired + LIVE-PROVEN]`
Goal: every video tells a genuinely new plot vs the channel's recent ones, by construction. Look/format/title style may stay consistent (brand) - only the plot must differ.
Seam: `originality.build_generation_guardrails(kind, recent_fingerprints)` produces the text appended to a generator's resolved system prompt. ``kind`` is "script" or "title" only.
- [x] **Script: point-of-view + new plot** (`pipeline_executor._load_prompt_overrides`): the script prompt now ALWAYS carries the point-of-view mandate (Wall 1), plus the recent-PLOTS block (Wall 2) when history exists. The hook diverges as part of a new plot. LIVE-PROVEN 2026-06-21 (same look + same title style: recycled plot -> RED/needs_reroll, new plot -> GREEN).
- [x] **Title: avoid reused plots** (`routes/discovery.py` line ~519): channel's own recent plots injected into the discovery title prompt before the `claude-sonnet-4-6` generate call, so new ideas don't duplicate a plot already made. (discovery already emits `formula_id` per option; storing it per produced video still owed.)
- [x] **Thumbnail: keep the style, never a template** (`pipeline_executor._load_prompt_overrides`, `originality.THUMBNAIL_ANTI_TEMPLATE`): the thumbnail prompt always carries an anti-template mandate (a consistent STYLE is fine; the COMPOSITION must vary), plus the recent thumbnail compositions to avoid when history exists. Per Ryan 2026-06-21: "thumbnails need to not be templated as well, the style can be the same but it can't look like a templated format."
- [~] **Visual-style divergence - DROPPED.** The visual STYLE may repeat (brand). Only the thumbnail COMPOSITION (above) and the script PLOT must vary.
- [ ] Explicit script format-rotation + single-source guard (still owed; lower priority since plot-divergence already covers the main signal).
Done when: generating 5 videos for one channel yields 5 genuinely different plots (look may match), with zero creator input.  ✅ core DONE + live-proven; live end-to-end pipeline run waits on a valid backend Anthropic key (now provided) + reachable DB.

## Phase 2 - Silent self-correction  `[built + live-proven]`
Goal: the rare recycled-plot draft fixes itself before proceeding - invisibly.
- [x] Script re-roll wired INSIDE `script/brief_translator/__init__.py` (right after `generate_script`, BEFORE any save / Google Doc / scene write — so no duplicate side effects) via `skills/video-pipeline/shared/originality_guard.maybe_reroll_for_plot`. It judges the draft's PLOT against the channel's recent plots (handed from the backend via the `RECENT_PLOTS_JSON` env seam, set in `_load_prompt_overrides`); on a recycled plot it regenerates with a "write a completely different plot" nudge, capped by `ORIGINALITY_MAX_REROLLS` (default 1). Invisible to the creator, fails open. Uses a DIRECT Sonnet call so it survives a Kie outage. LIVE-PROVEN 2026-06-21: recycled plot -> RED -> 1 regenerate -> distinct plot -> GREEN -> stop.
- [ ] (Optional) append re-roll notes to `agent_paper_trail` for our debugging.
Done when: a recycled-plot draft silently becomes a distinct one before it is ever saved.  ✅ DONE + live-proven.

## Phase 3 - Deep custom identity (super custom)  `[todo]`
Goal: each channel is genuinely distinct, and output isn't recognizably "engine-shaped" across tenants.
- [ ] Strengthen the clone/identity system so each channel's voice, angle, structure, and look form a distinct fingerprint (builds on the engine/identity split already shipped).
- [ ] Parameterize the craft templates deeply so two channels on the same topic produce clearly different videos.
Done when: two cloned channels on the same niche produce videos a reviewer would never mistake for the same operation.

## Phase 4 - Automatic disclosure  `[todo]`
Goal: realistic real-person / cloned-real-voice / altered-real-footage videos carry the label, automatically and invisibly.
- [ ] Detect those content types (voice-clone path in `dialogue_voice.py`; realistic-real-person signals from script/scene metadata); auto-set `ai_disclosure_required` + draft `ai_disclosure_text`.
- [ ] Auto-prepend disclosure to the YouTube description at upload. No creator action needed.
Done when: a cloned-real-voice video is labeled automatically; a fully fictional/animated video is not.

## Phase 5 - Internal observability (for us, not creators)  `[todo]`
Goal: we can confirm the diversity is actually working - the creator still sees nothing.
- [ ] A dev-only view/report: per-channel spread of title formulas, hook shapes, structures, thumbnails over recent videos, so we can verify the engine is diverging as designed and tune thresholds.
Done when: we can look at any channel and confirm its recent videos are genuinely varied.

---

## Open decisions (resolve while building)
- **N (history window):** how many recent videos each generator diverges from. Default 10.
- **Re-roll cap + fallback:** retries before accepting the best-of and moving on. Default 2.
- **Scorer v1 vs v2:** ship the cheap Claude-judge + deterministic checks first; add embeddings only if needed.

## Log
- 2026-06-21 - Phase 2 (silent re-roll) BUILT + LIVE-PROVEN, plus thumbnail anti-template. Ryan: "thumbnails need to not be templated as well, the style can be the same but it can't look like a templated format" -> re-added thumbnail injection as an anti-TEMPLATE mandate (style repeats, composition varies). Phase 2: `shared/originality_guard.maybe_reroll_for_plot` wraps `generate_script` inside `brief_translator` (before any save), judges the plot via a DIRECT Sonnet call (survives Kie outage) against `RECENT_PLOTS_JSON`, re-rolls a recycled plot with a harder nudge (cap `ORIGINALITY_MAX_REROLLS`, default 1), invisible + fail-open. Live test: recycled plot -> RED -> 1 regenerate -> distinct -> GREEN -> stop. All files compile. Ryan supplied a valid Anthropic key (used via env for tests; still needs adding to the VPS env + rotating since it was pasted in chat).
- 2026-06-21 - DESIGN CHANGE (Ryan): "every video can look the same, it just needs a completely different plot from the last one." Refocused the whole defense from "diverge on title/hook/thumbnail/look" to PLOT-only divergence. Look/format/title style may stay consistent (brand). Refactored `originality.py` (recent-PLOTS block, `distinct_plot` verdict field, plot-focused judge), dropped thumbnail injection in `pipeline_executor`, dropped the visual-look Phase 1 item. LIVE-PROVEN with a valid `claude-sonnet-4-6` key Ryan supplied: same look + same title style -> recycled plot = RED (re-roll), new plot = GREEN. NOTE: the supplied key was used via env for testing only (not persisted to any file); it still needs to be added to the VPS backend env for prod, and it was pasted in chat so it should be rotated.
- 2026-06-21 - Researched YouTube inauthentic-content policy. Audited pipeline, mapped every rule to a file. Ryan corrected the design: NO user-facing gates/warnings - safety must be baked into generation so slop is structurally impossible and the creator never worries. History-awareness moved from post-hoc judge to generation input; checks are silent internal re-rolls only. Plan rewritten.
- 2026-06-21 - Phase 1 (script + thumbnail + title) WIRED. `originality.build_generation_guardrails` appends the point-of-view mandate (Wall 1, always) + the recent-videos divergence block (Wall 2, when history) to the script and thumbnail prompts at `pipeline_executor._load_prompt_overrides`, and the recent-titles block to the discovery title prompt. All defensive (fail to no-op), invisible to the creator, applied on top of custom or neutral prompts. All edited files compile; guardrail builder unit-verified (script always gets POV; thumbnail/title only diverge with history). Live end-to-end run waits on a valid backend Anthropic key + reachable DB. Remaining Phase 1: visual-look divergence + explicit script format-rotation.
- 2026-06-21 - Phase 0 core BUILT + LIVE-PROVEN. `backend/originality.py` + migration 055 written. Verified end to end with a direct `claude-sonnet-4-6` cloud call (Ryan's call to use Sonnet): the judge nails a templated near-duplicate as RED (needs_reroll) with a concrete divergence suggestion, and a distinct opinionated draft as GREEN. CREDENTIAL NOTE: the StoryEngine working-tree `.env` is stale — its `ANTHROPIC_API_KEY` 401s (dead) and its `DATABASE_URL` points at a gone Supabase project. The live test used Ryan's UDC key for a one-off check only (NOT wired into StoryEngine). For this feature to run in prod, the backend env needs a VALID direct `ANTHROPIC_API_KEY` (the whole point is to bypass the banned Kie gateway). Next: Phase 1 (wire the diversity block + POV mandate into the title/hook/script/thumbnail generators).
