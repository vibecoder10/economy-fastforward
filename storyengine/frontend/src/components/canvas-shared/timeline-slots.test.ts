import { describe, expect, it } from "vitest";
import { buildTimelineSlots, type TimelineAssetInput, type TimelineSceneInput } from "./timeline-slots";
import { parseEnforcedPlan, parseShotPlan } from "./shot-plan-parsers";

/** Minimal valid scene row — every field callers care about defaults to
 *  "nothing here yet"; tests override only what they need. */
const SCENE_DEFAULTS: Omit<TimelineSceneInput, "scene"> = {
  coverage_directive: null,
  storyboard_1_url: null,
  storyboard_2_url: null,
  storyboard_3_url: null,
  storyboard_4_url: null,
  storyboard_5_url: null,
  storyboard_prompts: null,
  storyboard_beat_count: null,
  storyboard_status: null,
  storyboard_errors: null,
};

function scene(overrides: Partial<TimelineSceneInput> & { scene: number }): TimelineSceneInput {
  return { ...SCENE_DEFAULTS, ...overrides };
}

const ASSET_DEFAULTS: Omit<TimelineAssetInput, "scene" | "image_index"> = {
  image_url: null,
  video_clip_url: null,
  status: null,
};

function asset(overrides: Partial<TimelineAssetInput> & { scene: number; image_index: number }): TimelineAssetInput {
  return { ...ASSET_DEFAULTS, ...overrides };
}

/** Build a 2-panel BEAT block matching the REAL persisted shape
 *  (coverage_to_app.py's `_plan_sheet_prompts` + the "--- BEAT n ---"
 *  wrapper parseStoryboardPromptBlocks expects), one board, two panels. */
function beatBlock(board: number, panels: string[]): string {
  return `--- BEAT ${board} ---\n${panels.join("\n")}`;
}

function panelLine(panel: number, moment: number, shotType: string, desc: string): string {
  return `[${panel}] M${moment} ${shotType} — ${desc}`;
}

describe("buildTimelineSlots — parser verdict re-verification", () => {
  it("parseEnforcedPlan (BEAT blocks) matches the boards 1:1 even when the raw directive overshoots the budget", () => {
    // A raw coverage_directive that, unbudgeted, would describe MORE shots
    // than the boards actually drew — the exact "40 parsed vs 27 drawn"
    // shape the mission plan flags. Two moments, 3 shots each in the raw
    // text (master + 2 angles = would-be 6 panels if read directly)...
    const rawDirective =
      "[SET | a kitchen]\n" +
      '[MOMENT 1 | chopping] LINE: Chef | "Watch the knife."\n' +
      "- MASTER [WIDE]: chef chops at the counter\n" +
      "- ANGLE [CU]: knife on the board\n" +
      "- ANGLE [CU]: chef's focused eyes\n" +
      "[MOMENT 2 | plating] LINE: Chef | \"Almost done.\"\n" +
      "- MASTER [MS]: chef plates the dish\n" +
      "- ANGLE [CU]: garnish drop\n" +
      "- ANGLE [CU]: final plate\n";
    // ...but the ENFORCED plan (what actually got drawn, post-budget) only
    // kept the first shot of each moment — 2 panels, matching a 2-panel board.
    const enforcedPrompts = beatBlock(1, [
      panelLine(1, 1, "WIDE", "chef chops at the counter"),
      panelLine(2, 2, "MS", "chef plates the dish"),
    ]);

    const raw = parseShotPlan(rawDirective);
    const enforced = parseEnforcedPlan(enforcedPrompts);

    expect(raw?.shots.length).toBe(6); // the overshoot parseShotPlan would report
    expect(enforced?.length).toBe(2); // the boards' real truth

    // And buildTimelineSlots must follow the boards, not the raw directive:
    // an asset only exists for the 2 enforced panels (image_index 100, 101).
    const scenes = [scene({ scene: 1, coverage_directive: rawDirective, storyboard_prompts: enforcedPrompts, storyboard_beat_count: 1 })];
    const assets = [asset({ scene: 1, image_index: 100, image_url: "https://x/1.png" }), asset({ scene: 1, image_index: 101, image_url: "https://x/2.png" })];
    const blocks = buildTimelineSlots(scenes, assets);
    expect(blocks[0].slots.length).toBe(2); // NOT 6 — proves parseShotPlan's overshoot is not used for counting
    expect(blocks[0].slots.every((s) => s.state === "image")).toBe(true);
  });
});

describe("buildTimelineSlots — edge cases (required by the T1 brief)", () => {
  it("empty video: no scenes -> no blocks", () => {
    expect(buildTimelineSlots([], [])).toEqual([]);
  });

  it("scene with no storyboard yet: block is unexpanded, zero slots", () => {
    const blocks = buildTimelineSlots([scene({ scene: 1 })], []);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ scene: 1, expanded: false, hasOverflow: false, slots: [] });
  });

  it("board drawn, plan present, nothing generated yet: every slot is 'planned'", () => {
    const prompts = beatBlock(1, [panelLine(1, 1, "WIDE", "establishing"), panelLine(2, 1, "CU", "detail")]);
    const blocks = buildTimelineSlots([scene({ scene: 1, storyboard_prompts: prompts, storyboard_beat_count: 1 })], []);
    expect(blocks[0].expanded).toBe(true);
    expect(blocks[0].slots.map((s) => s.state)).toEqual(["planned", "planned"]);
    expect(blocks[0].slots.map((s) => s.expectedImageIndex)).toEqual([100, 101]);
    expect(blocks[0].slots.map((s) => s.asset)).toEqual([null, null]);
  });

  it("asset present with image but no clip -> state=image", () => {
    const prompts = beatBlock(1, [panelLine(1, 1, "WIDE", "establishing")]);
    const scenes = [scene({ scene: 1, storyboard_prompts: prompts, storyboard_beat_count: 1 })];
    const assets = [asset({ scene: 1, image_index: 100, image_url: "https://x/img.png" })];
    const blocks = buildTimelineSlots(scenes, assets);
    expect(blocks[0].slots[0].state).toBe("image");
    expect(blocks[0].slots[0].asset).toBe(assets[0]);
  });

  it("asset present with a clip -> state=clip (clip wins over image)", () => {
    const prompts = beatBlock(1, [panelLine(1, 1, "WIDE", "establishing")]);
    const scenes = [scene({ scene: 1, storyboard_prompts: prompts, storyboard_beat_count: 1 })];
    const assets = [asset({ scene: 1, image_index: 100, image_url: "https://x/img.png", video_clip_url: "https://x/clip.mp4" })];
    const blocks = buildTimelineSlots(scenes, assets);
    expect(blocks[0].slots[0].state).toBe("clip");
  });

  it("a row exists with no image yet -> state=pending (distinct from planned = no row at all)", () => {
    const prompts = beatBlock(1, [panelLine(1, 1, "WIDE", "establishing"), panelLine(2, 1, "CU", "detail")]);
    const scenes = [scene({ scene: 1, storyboard_prompts: prompts, storyboard_beat_count: 1 })];
    // Only panel 1 has a row (e.g. a retry-reset left it with no image);
    // panel 2 has no row at all yet.
    const assets = [asset({ scene: 1, image_index: 100, status: "pending" })];
    const blocks = buildTimelineSlots(scenes, assets);
    expect(blocks[0].slots[0].state).toBe("pending");
    expect(blocks[0].slots[1].state).toBe("planned");
  });

  it("video_status/animation_status failure markers -> state=failed with NO image present (real, live-written marker as of T5b)", () => {
    const prompts = beatBlock(1, [panelLine(1, 1, "WIDE", "establishing"), panelLine(2, 1, "CU", "detail")]);
    const scenes = [scene({ scene: 1, storyboard_prompts: prompts, storyboard_beat_count: 1 })];
    const assets = [
      asset({ scene: 1, image_index: 100, video_status: "failed" }),
      asset({ scene: 1, image_index: 101, animation_status: "error" }),
    ];
    const blocks = buildTimelineSlots(scenes, assets);
    expect(blocks[0].slots[0].state).toBe("failed");
    expect(blocks[0].slots[1].state).toBe("failed");
  });

  it("static_docu-format failure statuses also resolve to failed (real, verified marker — different scope than animation channels)", () => {
    const prompts = beatBlock(1, [panelLine(1, 1, "WIDE", "establishing")]);
    const scenes = [scene({ scene: 1, storyboard_prompts: prompts, storyboard_beat_count: 1 })];
    const assets = [asset({ scene: 1, image_index: 100, status: "qa_rejected" })];
    const blocks = buildTimelineSlots(scenes, assets);
    expect(blocks[0].slots[0].state).toBe("failed");
  });

  it("T5b (2026-07-28): a failed CLIP on an already-imaged shot shows failed, not image — this is the primary case T5b exists for", () => {
    // CHANGED from the pre-T5b precedence (image_url used to win over a
    // video/animation-stage marker, on the theory the marker might be
    // stale). That theory no longer holds: pipeline_executor.py's clip
    // success write clears video_status=NULL in the SAME statement as
    // video_clip_url, and the redraw path clears it too — so a picture
    // with an image_url AND a video_status failure marker, and NO clip,
    // can only mean "the most recent clip attempt on this exact image
    // failed and hasn't been retried since." That is precisely the shot a
    // creator needs the timeline to flag — the whole reason T5b exists (a
    // failed clip attempt was previously indistinguishable from "never
    // attempted"; showing "image" here would still be exactly that bug).
    const prompts = beatBlock(1, [panelLine(1, 1, "WIDE", "establishing")]);
    const scenes = [scene({ scene: 1, storyboard_prompts: prompts, storyboard_beat_count: 1 })];
    const assets = [asset({ scene: 1, image_index: 100, image_url: "https://x/img.png", video_status: "failed" })];
    const blocks = buildTimelineSlots(scenes, assets);
    expect(blocks[0].slots[0].state).toBe("failed");
  });

  it("a real clip still beats a failure marker (clip truth is the strongest signal, checked first, unconditionally)", () => {
    const prompts = beatBlock(1, [panelLine(1, 1, "WIDE", "establishing")]);
    const scenes = [scene({ scene: 1, storyboard_prompts: prompts, storyboard_beat_count: 1 })];
    const assets = [asset({
      scene: 1, image_index: 100, image_url: "https://x/img.png",
      video_clip_url: "https://x/clip.mp4", video_status: "failed",
    })];
    const blocks = buildTimelineSlots(scenes, assets);
    expect(blocks[0].slots[0].state).toBe("clip");
  });

  it("scene longer than 5 board sheets: overflow assets still surface as slots, honestly unlabeled (board=null, no plan metadata)", () => {
    // A realistic persisted plan: boards 1-5 each with one panel (parseEnforcedPlan's
    // own guard requires the plan to actually start at panel [1] — a lone
    // "BEAT 5" block with no board 1-4 ahead of it isn't a shape the real
    // backend ever produces, since coverage_to_app.py always numbers
    // sequentially from board 1). Panels 1-5 across the 5 sheets — the
    // preview cap (coverage_to_app.py ~L1911-1912, [:5]) means panel 6
    // never got a BEAT block, even though the picture pass drew it anyway
    // (~L1950-1952: "the pictures step still draws every planned shot from
    // the full text plan regardless; only the SHEET PREVIEW truncates").
    const prompts = [1, 2, 3, 4, 5].map((board) => beatBlock(board, [panelLine(board, board, "WIDE", `panel ${board}`)])).join("\n\n");
    const scenes = [scene({ scene: 1, storyboard_prompts: prompts, storyboard_beat_count: 5 })];
    const assets = [
      asset({ scene: 1, image_index: 99 + 5, image_url: "https://x/5.png" }), // last previewed panel
      asset({ scene: 1, image_index: 99 + 6, image_url: "https://x/6.png" }), // beyond the preview — overflow
    ];
    const blocks = buildTimelineSlots(scenes, assets);
    // 5 planned panels (only panel 5 has an asset) + 1 overflow panel = 6.
    expect(blocks[0].slots).toHaveLength(6);
    expect(blocks[0].slots.filter((s) => s.state === "planned")).toHaveLength(4);
    expect(blocks[0].hasOverflow).toBe(true);
    const overflow = blocks[0].slots.find((s) => s.panel === 6)!;
    expect(overflow.board).toBeNull();
    expect(overflow.plan).toBeNull();
    expect(overflow.state).toBe("image");
    // The previewed panel keeps its rich plan metadata and real board number.
    const previewed = blocks[0].slots.find((s) => s.panel === 5)!;
    expect(previewed.board).toBe(5);
    expect(previewed.plan).not.toBeNull();
  });

  it("stale plan input is ignored: the function never reads scene_text or coverage_directive_hash, so it cannot and does not detect staleness (documented client-invisible limitation)", () => {
    const prompts = beatBlock(1, [panelLine(1, 1, "WIDE", "establishing")]);
    // Two scene rows identical except for `coverage_directive` (which this
    // function deliberately never reads) — output must be byte-identical,
    // proving there is no hidden staleness check reading that field either.
    const staleScenes = [scene({ scene: 1, storyboard_prompts: prompts, storyboard_beat_count: 1, coverage_directive: "OLD TEXT completely different from what drew this plan" })];
    const freshScenes = [scene({ scene: 1, storyboard_prompts: prompts, storyboard_beat_count: 1, coverage_directive: "brand new text" })];
    const assets = [asset({ scene: 1, image_index: 100, image_url: "https://x/1.png" })];
    expect(buildTimelineSlots(staleScenes, assets)).toEqual(buildTimelineSlots(freshScenes, assets));

    // And there is no way to even express a hash on the input type — this
    // is a type-level assertion that TimelineSceneInput carries no such
    // field, not just a runtime one.
    type HasHash = "coverage_directive_hash" extends keyof TimelineSceneInput ? true : false;
    const assertion: HasHash = false;
    expect(assertion).toBe(false);
  });

  it("multiple scenes are each their own independent block, sorted by scene number", () => {
    const p1 = beatBlock(1, [panelLine(1, 1, "WIDE", "s1")]);
    const p2 = beatBlock(1, [panelLine(1, 1, "WIDE", "s2")]);
    const scenes = [
      scene({ scene: 2, storyboard_prompts: p2, storyboard_beat_count: 1 }),
      scene({ scene: 1, storyboard_prompts: p1, storyboard_beat_count: 1 }),
    ];
    const blocks = buildTimelineSlots(scenes, []);
    expect(blocks.map((b) => b.scene)).toEqual([1, 2]);
  });
});
