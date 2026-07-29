/**
 * Timeline Workbench — chunk T1: the timeline slot model.
 *
 * Pure function, no network, no React, no rendering: script rows + asset
 * rows in, a per-scene "storyboard block" with its ordered slot list out.
 * T2 (a later chunk) is responsible for rendering this on the timeline.
 *
 * ---------------------------------------------------------------------
 * PARSER VERDICT (re-verified against real code, 2026-07-28) — read this
 * before touching the panel-numbering logic below.
 * ---------------------------------------------------------------------
 *
 * CANONICAL: `parseEnforcedPlan(storyboard_prompts)` from ./shot-plan-parsers.
 * NEVER: `parseShotPlan(coverage_directive)` for slot/image_index mapping.
 *
 * Why, with receipts:
 *
 * 1. shot-plan-parsers.ts's own docstring on parseEnforcedPlan already
 *    records the discrepancy this chunk was asked to re-verify: "The raw
 *    directive can contain MORE shots than the budget allows (planner
 *    overshoot), so parsing it showed "40 shots" while the boards draw
 *    27 — the BEAT blocks are post-budget and match the boards 1:1."
 *
 * 2. Backend confirms the same thing from the writer side. In
 *    backend/scripts/coverage_to_app.py, `store_scene()` (~L482-555)
 *    assigns each drawn frame's `image_index` by starting at
 *    `COVERAGE_INDEX_BASE = 100` (~L118, comment: "existing panels use
 *    1-9; coverage frames live at 100+") and incrementing by 1 per frame,
 *    in the SAME order the plan was drawn in. The plan that gets drawn is
 *    the post-budget, post-floor, post-variety `moments` list
 *    (`plan_moments_deterministic`, ~L1890) — the exact same function and
 *    order the BEAT-block sheet preview is built from (the code comment
 *    at ~L1885 says this explicitly: "the SAME deterministic pipeline
 *    (and order) run_coverage() runs on this exact directive_text at
 *    picture-draw time — the sheet preview built below from `moments`...
 *    can no longer disagree"). So `image_index = 99 + panel` where
 *    `panel` is the BEAT block's 1-based `[k]` label — never the raw
 *    `coverage_directive`'s shot count, which `parseShotPlan` reads
 *    straight off the pre-budget directive text and can overshoot.
 *
 * 3. `parseShotPlan` is still the right tool for a DIFFERENT job — a
 *    prose "read the plan before you draw" preview
 *    (ScenesWorkspaceTab.tsx's ShotPlanViewer, ~L112-119) that falls back
 *    to it only when no storyboard sheets have been drawn yet, and even
 *    then just guesses a display board number
 *    (`Math.ceil(s.panel / 12)`, not authoritative — real sheets don't
 *    always chunk at 12 panels; see `panels_per_sheet_for`). That's fine
 *    for prose. It is NOT fine here: T1 ties panel numbers directly to
 *    real `assets.image_index` values, and a wrong number here means
 *    matching a slot to the wrong asset row (or none at all).
 *
 * Net: this file parses `storyboard_prompts` with `parseEnforcedPlan`
 * only. A scene with a `coverage_directive` but no `storyboard_prompts`
 * yet (sheets never drawn) has no reliable panel numbering available to
 * the frontend, so its block is UNEXPANDED (see below) rather than
 * guessed from the raw directive.
 *
 * ---------------------------------------------------------------------
 * THE >5-BOARD-SHEET CASE — decided and documented, not guessed.
 * ---------------------------------------------------------------------
 *
 * `storyboard_prompts` itself is truncated. In coverage_to_app.py's plan
 * step (~L1911-1912): `_previewed = sum(_sizes[:5])` and
 * `prompts = _plan_sheet_prompts(moments, ...)[:5]` — only the first 5
 * board SHEETS ever get a BEAT block persisted, even though `shot_count`
 * (the full plan) can be larger. The code says so directly (~L1950-1952):
 * "A scene over 5 boards' worth of panels... previews only its FIRST
 * sum(_sizes[:5]) shots... The pictures step still draws every planned
 * shot from the full text plan regardless; only the SHEET PREVIEW
 * truncates." So a >5-board scene ends up with MORE real `assets` rows
 * (once pictures are drawn) than `parseEnforcedPlan` can ever describe —
 * the frontend has no parser for panels beyond the 5th sheet; that text
 * was never persisted anywhere it can read.
 *
 * Honest behavior chosen here: panel count and slot count are allowed to
 * differ. Every asset row whose derived panel number falls beyond the
 * highest panel `parseEnforcedPlan` describes is still surfaced as a real
 * slot ("overflow") — `board: null` (no board sheet shows it), full
 * fill-state (image/clip/failed/pending) still computed from the asset
 * row, but no rich plan metadata (shot type, dialogue, description)
 * because that text genuinely does not exist on the client. A board
 * block's `hasOverflow` flag says whether this happened.
 * Known gap (documented, not solved here): a >5-board scene's overflow
 * shots are entirely invisible during `plan_only` — they only appear
 * once pictures are actually drawn and their asset rows exist. There is
 * no way for this pure function to predict them ahead of that; T2/T5
 * should not promise a slot exists before an asset backs it.
 *
 * ---------------------------------------------------------------------
 * STATE MACHINE — planned | pending | image | clip | failed
 * ---------------------------------------------------------------------
 *
 * Precedence (first match wins), computed per slot from its matched
 * asset row (matched by `image_index === 99 + panel`):
 *
 *   no matching asset row exists                    -> "planned"
 *   asset.video_clip_url is set                      -> "clip"
 *   asset carries a video/animation failure marker   -> "failed"  (T5b)
 *   asset.image_url is set                            -> "image"
 *   asset carries an image-stage failure marker       -> "failed"  (static_docu)
 *   otherwise (asset row exists, no image)            -> "pending"
 *
 * CHANGED 2026-07-28 (T5b): the video/animation-marker check now runs
 * BEFORE the `image_url` check, not after. Read the STATE MACHINE section
 * below for why — short version: a clip is generated FROM an existing
 * image, so `image_url` being set is never evidence a clip attempt
 * succeeded, and T5b's backend write (pipeline_executor.py) guarantees
 * `video_status`/`animation_status` can no longer go stale the way the old
 * ordering assumed.
 *
 * "planned" vs "pending" is a real, verifiable distinction in the data
 * model, not an invented one: `store_scene()` (coverage_to_app.py
 * ~L494-497) only ever INSERTs an asset row once a frame has actually
 * been drawn (`status='done'` in the same INSERT that sets `image_url`).
 * Nothing in the live coverage/clip pipeline inserts a placeholder row
 * ahead of drawing. So "no row at that image_index" genuinely means
 * "nothing has been attempted yet" (planned), while "a row exists but
 * image_url is still null" means something did leave a row there without
 * a picture — today that's mainly the explicit retry-reset path
 * (pipeline_executor.py ~L15164: `UPDATE assets SET status = 'pending'
 * WHERE ... image_url IS NULL`) — hence "pending".
 *
 * IMPORTANT, re-verified honestly (do not "fix" this without re-reading
 * the code first): "pending" here can only ever mean "a row exists
 * without a picture yet". It does NOT mean "a generation is running
 * right now". Concurrency claims for in-flight clip generation live in
 * `clip_asset_claims.py` as an in-process `dict`, scoped to the seconds a
 * single API worker is animating a shot — never written to the `assets`
 * row, never visible to a poll of this table. A live "generating..."
 * spinner (T5) will need a signal this function's inputs do not carry;
 * this function alone cannot tell "queued" from "actively rendering".
 *
 * "failed" — real coverage as of T5b (2026-07-28), verified by reading the
 * actual write paths, not guessed:
 *   - `assets.status` values 'blocked_no_reference' / 'budget_capped' /
 *     'qa_rejected' (static_docu.py only, ~L1706/1747/1840) ARE real,
 *     persisted failure markers — but only for the static-documentary
 *     format, which is explicitly out of scope for this mission's
 *     animation-channel build (see TIMELINE-WORKBENCH-PLAN.md's DvsU
 *     caveat). Still checked below since a slot from a static_docu-format
 *     scene, if one ever flows through this function, should show failed
 *     rather than silently misreport pending. Checked AFTER `image_url`
 *     (unchanged) — an image-stage failure only means anything when no
 *     image ever landed.
 *   - `assets.video_status` — a real Postgres column
 *     (migrations/000_baseline_schema.sql) that the live clip-generation
 *     path now genuinely writes: `pipeline_executor.py`'s `_safe_one`
 *     except branch sets it to `'failed'` on an isolated clip error (T5b),
 *     and BOTH the success write (same statement as `video_clip_url`) and
 *     the redraw path (coverage_to_app.py) clear it back to NULL. That
 *     clear-on-success/clear-on-redraw guarantee is exactly why this check
 *     now runs BEFORE `image_url` below: a clip is animated FROM an
 *     existing image, so `image_url` being set was never real evidence a
 *     clip attempt succeeded, and the marker can no longer go stale the
 *     way the pre-T5b ordering (image wins) assumed when it was purely
 *     defensive/speculative.
 *   - `assets.animation_status` is the same real column, still unwritten by
 *     any live path today (only `supabase_adapter.py`, a separate
 *     Airtable-facing adapter) — checked defensively alongside
 *     `video_status` so it activates automatically if that ever changes,
 *     with zero further changes here.
 *
 * ---------------------------------------------------------------------
 * STALE PLAN (coverage_directive_hash) — genuinely client-invisible.
 * ---------------------------------------------------------------------
 * The backend tracks staleness via `scripts.coverage_directive_hash`
 * (migrations/078_coverage_directive.sql; read/compared in
 * coverage_to_app.py ~L1873 and ~L3507 against a hash of the live
 * scene_text). That column is NEVER selected into the frontend's
 * `ScriptScene` type (lib/api.ts) — no route exposes it. This function
 * therefore cannot detect "the plan is stale vs. the current script
 * text" and does not attempt to; it only reads what it's given
 * (`storyboard_prompts`, `assets`), never `scene_text`. See the
 * "stale plan input is ignored" test below, which pins this limitation
 * down instead of leaving it as an assumption.
 *
 * ---------------------------------------------------------------------
 * SCOPE BOUNDARY: coverage assets only.
 * ---------------------------------------------------------------------
 * `image_index` values 1-9 belong to an older, pre-coverage picture path
 * (see COVERAGE_INDEX_BASE's own comment: "existing panels use 1-9").
 * This function only ever matches `image_index >= COVERAGE_INDEX_BASE`
 * (100) — a scene that never went through the storyboard/coverage flow
 * has nothing to show on the Timeline Workbench and correctly renders as
 * an empty, unexpanded block.
 */

import { parseEnforcedPlan } from "./shot-plan-parsers";

/** existing panels use 1-9; coverage frames live at 100+ (never clobber).
 *  Mirrors backend/scripts/coverage_to_app.py's COVERAGE_INDEX_BASE. */
const COVERAGE_INDEX_BASE = 100;

// ---------------------------------------------------------------------
// Input shapes — deliberately local, narrow mirrors of the fields this
// function actually reads out of lib/api.ts's `ScriptScene` and `Asset`.
// Kept local (not imported from lib/api.ts) so this stays a zero-import,
// zero-dependency pure module and the diff to the rest of the app stays
// additive — a real ScriptScene/Asset object satisfies these structurally
// (every field here exists on those types with the same name and type;
// the two speculative fields are optional so their absence is fine too).
// ---------------------------------------------------------------------

export interface TimelineSceneInput {
  scene: number | null;
  coverage_directive: string | null;
  storyboard_1_url: string | null;
  storyboard_2_url: string | null;
  storyboard_3_url: string | null;
  storyboard_4_url: string | null;
  storyboard_5_url: string | null;
  storyboard_prompts: string | null;
  storyboard_beat_count: number | null;
  storyboard_status: string | null;
  /** Per-board sheet draw failures, keyed by beat number as a string
   *  ("1".."5"). Board-level, not slot-level — see TimelineStoryboardBlock
   *  .sheetErrors. Optional here only for structural looseness; the real
   *  ScriptScene type always has the key (possibly null). */
  storyboard_errors?: Record<string, { class?: string; msg?: string | null }> | null;
}

export interface TimelineAssetInput {
  scene: number | null;
  image_index: number | null;
  image_url: string | null;
  video_clip_url: string | null;
  status: string | null;
  /** Real Postgres columns, NOT on lib/api.ts's Asset type and NOT
   *  written by the live coverage/clip pipeline as of 2026-07-28 — see
   *  the file header's STATE MACHINE section. Checked defensively. */
  video_status?: string | null;
  animation_status?: string | null;
}

export type SlotState = "planned" | "pending" | "image" | "clip" | "failed";

export interface TimelineSlotPlanInfo {
  /** 1-based moment number this shot belongs to (parseEnforcedPlan's `moment`). */
  moment: number;
  role: string; // "MASTER" | "ANGLE"
  shotType: string;
  speaker: string | null;
  line: string | null;
  desc: string;
}

export interface TimelineSlot {
  scene: number;
  /** Which board sheet (1-based, 1-5) this slot's plan text came from.
   *  null for an "overflow" slot: a real asset exists beyond the highest
   *  panel the persisted plan describes (see the >5-board-sheet section
   *  above) — or, for a scene whose plan didn't parse at all but whose
   *  assets exist anyway (defensive fallback, same reasoning). */
  board: number | null;
  /** 1-based global panel number — matches the board sheets' `[k]` label
   *  and `image_index - (COVERAGE_INDEX_BASE - 1)`. */
  panel: number;
  /** The asset row this slot expects to find, per the verified mapping
   *  `image_index = 99 + panel` (COVERAGE_INDEX_BASE=100, panel starts at 1). */
  expectedImageIndex: number;
  asset: TimelineAssetInput | null;
  state: SlotState;
  /** Rich plan metadata when available (from parseEnforcedPlan). Absent
   *  for overflow slots — that text was never persisted anywhere the
   *  frontend can read (see the >5-board-sheet section above). */
  plan: TimelineSlotPlanInfo | null;
}

export interface TimelineStoryboardBlock {
  scene: number;
  storyboardStatus: string | null;
  /** storyboard_1_url .. storyboard_5_url, in order. */
  boardUrls: (string | null)[];
  /** Number of board sheets this scene actually has, from
   *  `storyboard_beat_count` when present (itself capped at 5 — see the
   *  parser verdict above) else derived from the parsed plan's highest
   *  board number, else 0. */
  boardCount: number;
  /** True once there is at least one slot to show (a parseable plan, or
   *  at least one coverage asset row) — false is the honest "no
   *  storyboard yet" empty state: nothing to expand. */
  expanded: boolean;
  /** True when at least one slot is an "overflow" slot (asset exists
   *  beyond what the persisted plan describes — see the >5-board-sheet
   *  section above). */
  hasOverflow: boolean;
  /** Per-board sheet draw failures (storyboard_errors), pass-through,
   *  keyed by beat number string. Board-level — distinct from a slot's
   *  own `state`, which only reflects that slot's own asset row. */
  sheetErrors: Record<string, { class?: string; msg?: string | null }> | null;
  slots: TimelineSlot[];
}

/** Failure markers checked on assets.status / video_status / animation_status.
 *  See the file header's STATE MACHINE section for exactly what's verified
 *  vs. defensive/speculative among these. */
const FAILURE_MARKERS = new Set([
  // Verified, real, persisted — but static_docu-format only (out of scope
  // for this mission's animation-channel build; checked anyway so a
  // static_docu row never silently misreports as pending).
  "blocked_no_reference",
  "budget_capped",
  "qa_rejected",
  // Speculative — no confirmed writer in the live animation-channel path
  // as of 2026-07-28 (see header). Checked so this activates automatically
  // if that ever changes.
  "failed",
  "error",
]);

function isFailureMarker(value: string | null | undefined): boolean {
  if (!value) return false;
  return FAILURE_MARKERS.has(value.trim().toLowerCase());
}

function deriveState(asset: TimelineAssetInput | null): SlotState {
  if (!asset) return "planned";
  if (asset.video_clip_url) return "clip";
  // T5b: video/animation-stage failure checked BEFORE image_url — a clip is
  // generated FROM an existing image, so having one is never evidence a
  // clip attempt succeeded. See the file header's STATE MACHINE section for
  // why this is now safe (the marker can no longer go stale).
  if (isFailureMarker(asset.video_status) || isFailureMarker(asset.animation_status)) {
    return "failed";
  }
  if (asset.image_url) return "image";
  // Image-stage failure (static_docu only) — only meaningful when no image
  // ever landed; unchanged from before T5b.
  if (isFailureMarker(asset.status)) return "failed";
  return "pending";
}

/** Build the per-scene storyboard blocks + slot lists for the Timeline
 *  Workbench. Pure: no fetch, no React, no side effects. See the file
 *  header for the parser verdict, the state-machine rules, and the
 *  >5-board-sheet decision — read those before changing this function. */
export function buildTimelineSlots(
  scenes: TimelineSceneInput[],
  assets: TimelineAssetInput[],
): TimelineStoryboardBlock[] {
  const blocks: TimelineStoryboardBlock[] = [];

  const sortedScenes = scenes
    .filter((s): s is TimelineSceneInput & { scene: number } => s.scene != null)
    .slice()
    .sort((a, b) => a.scene - b.scene);

  for (const scene of sortedScenes) {
    const sceneNumber = scene.scene;

    // Coverage assets for this scene only (scope boundary: image_index >= 100
    // — see file header). Assets input order is preserved for a deterministic
    // tie-break if duplicate image_index rows ever exist for the same scene.
    const sceneAssets = assets.filter(
      (a) => a.scene === sceneNumber && a.image_index != null && a.image_index >= COVERAGE_INDEX_BASE,
    );
    const assetsByImageIndex = new Map<number, TimelineAssetInput>();
    for (const a of sceneAssets) {
      if (a.image_index != null && !assetsByImageIndex.has(a.image_index)) {
        assetsByImageIndex.set(a.image_index, a);
      }
    }

    // CANONICAL parser only — see file header's PARSER VERDICT.
    const enforced = parseEnforcedPlan(scene.storyboard_prompts);

    const slots: TimelineSlot[] = [];
    let maxPlannedPanel = 0;

    if (enforced) {
      for (const shot of enforced) {
        const expectedImageIndex = COVERAGE_INDEX_BASE - 1 + shot.panel;
        const asset = assetsByImageIndex.get(expectedImageIndex) ?? null;
        slots.push({
          scene: sceneNumber,
          board: shot.board,
          panel: shot.panel,
          expectedImageIndex,
          asset,
          state: deriveState(asset),
          plan: {
            moment: shot.moment,
            role: shot.role,
            shotType: shot.shotType,
            speaker: shot.speaker,
            line: shot.line,
            desc: shot.desc,
          },
        });
        if (shot.panel > maxPlannedPanel) maxPlannedPanel = shot.panel;
      }
    }

    // Overflow: real asset rows beyond the highest panel the plan describes
    // (>5-board-sheet scenes — see file header), OR every coverage asset
    // when the plan didn't parse at all but pictures exist anyway (a scene
    // drawn through some other path than the sheet-anchored one this
    // parser expects). Either way: the asset is real, so the slot is real.
    const overflowIndexes = Array.from(assetsByImageIndex.keys())
      .filter((idx) => idx - (COVERAGE_INDEX_BASE - 1) > maxPlannedPanel)
      .sort((a, b) => a - b);
    let hasOverflow = false;
    for (const idx of overflowIndexes) {
      hasOverflow = true;
      const asset = assetsByImageIndex.get(idx) ?? null;
      slots.push({
        scene: sceneNumber,
        board: null,
        panel: idx - (COVERAGE_INDEX_BASE - 1),
        expectedImageIndex: idx,
        asset,
        state: deriveState(asset),
        plan: null,
      });
    }

    slots.sort((a, b) => a.panel - b.panel);

    const boardUrls = [
      scene.storyboard_1_url,
      scene.storyboard_2_url,
      scene.storyboard_3_url,
      scene.storyboard_4_url,
      scene.storyboard_5_url,
    ];
    const highestBoardFromPlan = slots.reduce((max, s) => (s.board != null && s.board > max ? s.board : max), 0);
    const boardCount = scene.storyboard_beat_count ?? highestBoardFromPlan;

    blocks.push({
      scene: sceneNumber,
      storyboardStatus: scene.storyboard_status,
      boardUrls,
      boardCount,
      expanded: slots.length > 0,
      hasOverflow,
      sheetErrors: scene.storyboard_errors ?? null,
      slots,
    });
  }

  return blocks;
}
