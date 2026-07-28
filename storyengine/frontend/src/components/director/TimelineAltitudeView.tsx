"use client";

import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Clock, Film, ImageOff, AlertTriangle, MicOff, Music, Play } from "lucide-react";
import { getVideoAssets, getVideoScript, getVideo, type Asset, type ScriptScene } from "@/lib/api";
import { toDisplayImageUrl, toDisplayVideoUrl } from "@/lib/utils";
import { buildTimelineSlots, type TimelineSlot, type TimelineStoryboardBlock } from "@/components/canvas-shared/timeline-slots";
import { CanvasEmptyState } from "./CanvasEmptyState";

/**
 * Timeline altitude (Chunk T2, LAYOUT CORRECTION 2026-07-28). Ryan rejected
 * the first build (a vertical stack of storyboard cards) with an OpenArt
 * director-suite screenshot: "thats not a timeline, this is a timeline."
 * This is the rebuild: a real HORIZONTAL track-based editor timeline docked
 * at the BOTTOM of the canvas, with the player/preview above it — see
 * TIMELINE-WORKBENCH-PLAN.md's "LAYOUT CORRECTION" section for the binding
 * spec, and its two follow-up amendments (in-track horizontal expand,
 * playhead).
 *
 * THE DATA LAYER DID NOT CHANGE. `buildTimelineSlots` (T1,
 * canvas-shared/timeline-slots.ts) is used exactly as before — same
 * scenes-in/assets-in, same per-scene block + slot list out, same overflow
 * handling, same two bugs this chunk already found and fixed live
 * (misleading "Not drawn yet" subtitle for a scene whose sheet exists but
 * whose plan text doesn't parse; a broken/stale image URL revealing an
 * unstyled native alt-text overflow instead of a muted fallback). Only the
 * LAYOUT changed: everything below reads that same block/slot data into a
 * horizontal filmstrip instead of a vertical card stack.
 *
 * Data sources — all already fetched on this surface, no new endpoint:
 *   - `["video-script", videoId]` (SceneAltitudeView, RightRail) — also the
 *     source of each scene's `voice_over_url` for the narration lane.
 *   - `["video-assets", videoId]` (SceneAltitudeView, RightRail).
 *   - `["video", videoId]` (CanvasHeader, SceneAltitudeView) — read here
 *     only for `final_video_url`, to drive the player region when a
 *     rendered video exists. Same cache key those already populate, so this
 *     is a cache hit, not a new request, whenever CanvasHeader is mounted
 *     (it always is — see DirectorSurface.tsx).
 *
 * LOCKED DECISIONS held from the original T2 brief (still true):
 *   - "Storyboard N" = scene N. A multi-sheet scene is still one segment.
 *   - Read-only: zero generate/animate/approve affordances anywhere here.
 *   - Overflow slots (board:null) are real and shown, grouped, with their
 *     real fill state — just inline on the track now, not under a heading.
 *   - "failed" renders subtly, never as a badge that promises to fire
 *     reliably (T1 proved the live clip-failure path doesn't persist one).
 *
 * NEW in the layout correction — the honest ruler rule:
 *   Real timecodes ONLY when real per-shot durations exist for literally
 *   every slot in the video (checked defensively off `assets.video_duration`
 *   / `assets.assigned_video_duration` / `assets.duration_seconds` — see
 *   `getRealDurationSeconds` below). Verified live against real prod data
 *   while building this: as of 2026-07-28, `duration_seconds` is null for
 *   every coverage-range asset in every video checked (it's only ever
 *   populated for the OLD pre-coverage picture path, and never alongside a
 *   clip); `video_duration`/`assigned_video_duration` DO carry real per-clip
 *   seconds in the database (confirmed with `se db` against
 *   973c9bd6-1fc7-43d8-802a-83a743a48d66's scene 1 — real values like 6, 7,
 *   9, 10 seconds), but neither field is serialized by
 *   `GET /api/videos/{id}/assets` today (confirmed with a direct curl of the
 *   real response — the JSON simply doesn't have those keys). So today,
 *   every real video's ruler correctly falls back to sequence markers
 *   ("Scene 1", "Scene 2"...), including 973c9bd6 — NOT because this view
 *   is broken, but because no video's real duration data reaches the
 *   frontend yet. Filed as a tiny, obviously-safe backend follow-up (expose
 *   those two columns on the existing assets serializer — no new endpoint)
 *   rather than fabricated around; the code below is written to activate a
 *   real proportional ruler automatically the day that lands, with zero
 *   further frontend changes.
 */

// ---------------------------------------------------------------------
// Sizing constants — visual tuning only, not a claimed precision.
// ---------------------------------------------------------------------
const CELL = 64; // matches SlotTile's h-16 w-16
const CELL_GAP = 4; // tailwind gap-1
const COLLAPSE_TAB_W = 28;
const OVERFLOW_DIVIDER_W = 40;
const ORDINAL_BASE_W = 96;
const ORDINAL_PER_SHOT_W = 9;
const ORDINAL_MAX_W = 240;
const ORDINAL_EMPTY_W = 104; // a scene with nothing yet still occupies a track segment
const PX_PER_SECOND = 16;
const MIN_REAL_SEG_W = 60;

/** Reads a real per-shot duration off an `Asset` row, defensively — none of
 *  these three fields are guaranteed present (see the file header). Checked
 *  in priority order: an explicit editorial override, then the model's
 *  actual render duration, then the older `duration_seconds` field (which,
 *  live-verified, only ever carries a value for the pre-coverage picture
 *  path — kept here anyway so this activates automatically if that ever
 *  changes for coverage clips too). Never invents a number: a non-finite or
 *  non-positive value is treated as "no real duration," same as absent. */
function getRealDurationSeconds(asset: Asset): number | null {
  const raw = asset as unknown as {
    assigned_video_duration?: unknown;
    video_duration?: unknown;
    duration_seconds?: unknown;
  };
  const candidate = raw.assigned_video_duration ?? raw.video_duration ?? raw.duration_seconds;
  const n = typeof candidate === "number" ? candidate : typeof candidate === "string" ? parseFloat(candidate) : NaN;
  return Number.isFinite(n) && n > 0 ? n : null;
}

function formatMMSS(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function tickIntervalSeconds(totalSeconds: number): number {
  if (totalSeconds <= 40) return 5;
  if (totalSeconds <= 120) return 10;
  if (totalSeconds <= 400) return 30;
  return 60;
}

export function TimelineAltitudeView({ videoId }: { videoId: string }) {
  const scriptQuery = useQuery({
    queryKey: ["video-script", videoId],
    queryFn: () => getVideoScript(videoId),
  });
  const assetsQuery = useQuery({
    queryKey: ["video-assets", videoId],
    queryFn: () => getVideoAssets(videoId),
  });
  // Shared cache — CanvasHeader.tsx and SceneAltitudeView.tsx already fetch
  // this exact key; only `final_video_url` (player region) is new to read
  // off it here.
  const videoQuery = useQuery({
    queryKey: ["video", videoId],
    queryFn: () => getVideo(videoId),
  });

  const blocks = useMemo(
    () => buildTimelineSlots(scriptQuery.data ?? [], assetsQuery.data ?? []),
    [scriptQuery.data, assetsQuery.data],
  );

  const assetsByKey = useMemo(() => {
    const m = new Map<string, Asset>();
    for (const a of assetsQuery.data ?? []) {
      if (a.scene != null && a.image_index != null) m.set(`${a.scene}:${a.image_index}`, a);
    }
    return m;
  }, [assetsQuery.data]);

  const durationForSlot = useCallback(
    (slot: TimelineSlot): number | null => {
      const asset = assetsByKey.get(`${slot.scene}:${slot.expectedImageIndex}`);
      return asset ? getRealDurationSeconds(asset) : null;
    },
    [assetsByKey],
  );

  const scriptByScene = useMemo(() => {
    const m = new Map<number, ScriptScene>();
    for (const s of scriptQuery.data ?? []) {
      if (s.scene != null) m.set(s.scene, s);
    }
    return m;
  }, [scriptQuery.data]);

  // Binary, all-or-nothing rule on purpose: a ruler mixing real seconds for
  // some scenes and invented-looking placeholders for others would be worse
  // than an honest "no timing yet" — see the file header for why this is
  // unreachable with today's real data (not a bug in this check).
  const rulerMode: "real" | "sequence" = useMemo(() => {
    let sawAny = false;
    for (const block of blocks) {
      for (const slot of block.slots) {
        sawAny = true;
        if (durationForSlot(slot) == null) return "sequence";
      }
    }
    return sawAny ? "real" : "sequence";
  }, [blocks, durationForSlot]);

  // Expansion is component-local on purpose — persisting which storyboards
  // are unpacked is T3's job (see the chunk brief), not this one's.
  const [expandedScenes, setExpandedScenes] = useState<Set<number>>(new Set());
  const toggleScene = (scene: number) => {
    setExpandedScenes((prev) => {
      const next = new Set(prev);
      if (next.has(scene)) next.delete(scene);
      else next.add(scene);
      return next;
    });
  };

  const segmentWidths = useMemo(() => {
    const m = new Map<number, number>();
    for (const block of blocks) {
      if (expandedScenes.has(block.scene) && block.expanded) {
        m.set(block.scene, expandedRunWidth(block));
      } else if (rulerMode === "real") {
        const totalSec = block.slots.reduce((sum, s) => sum + (durationForSlot(s) ?? 0), 0);
        m.set(block.scene, block.slots.length === 0 ? ORDINAL_EMPTY_W : Math.max(MIN_REAL_SEG_W, Math.round(totalSec * PX_PER_SECOND)));
      } else {
        m.set(block.scene, ordinalCollapsedWidth(block));
      }
    }
    return m;
  }, [blocks, expandedScenes, rulerMode, durationForSlot]);

  const isLoading = scriptQuery.isLoading || assetsQuery.isLoading;
  const isError = scriptQuery.isError || assetsQuery.isError;
  const finalVideoUrl = videoQuery.data?.final_video_url ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Player/preview region — the area ABOVE the docked timeline, per the
          layout correction. Plays the real rendered output when it exists
          (videos.final_video_url, same ["video", videoId] cache
          CanvasHeader already populates); otherwise the same "Your video
          will land here" placeholder the rest of the app already uses. */}
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-void p-4">
        {finalVideoUrl ? (
          <video
            key={finalVideoUrl}
            src={toDisplayVideoUrl(finalVideoUrl)}
            controls
            className="max-h-full max-w-full rounded-card border border-line-soft bg-black"
          />
        ) : (
          <div className="h-full w-full">
            <CanvasEmptyState />
          </div>
        )}
      </div>

      {/* Docked editor timeline — bottom of the canvas, fixed height. */}
      <div className="flex h-[266px] flex-none flex-col border-t border-line-soft bg-surface">
        <div className="flex h-9 flex-none items-center gap-2.5 border-b border-line-soft px-3">
          <button type="button" disabled title="Play — not available yet" className="flex h-6 w-6 flex-none items-center justify-center rounded-card-sm text-faint opacity-50">
            <Play size={12} />
          </button>
          <span className="text-[11.5px] font-semibold text-ink">Timeline</span>
          <span className="text-[10.5px] text-faint">
            {rulerMode === "real" ? "Real timecodes" : "Sequence order — no real durations yet"}
          </span>
          <div className="ml-auto flex flex-none items-center gap-1.5">
            <button type="button" disabled title="Zoom — not available yet" className="h-6 rounded-[7px] border border-line-soft bg-raise px-2 text-[10.5px] font-medium text-ink opacity-40">
              −
            </button>
            <button type="button" disabled title="Zoom — not available yet" className="h-6 rounded-[7px] border border-line-soft bg-raise px-2 text-[10.5px] font-medium text-ink opacity-40">
              +
            </button>
          </div>
        </div>

        {isLoading && <div className="flex-1 py-8 text-center text-sm text-faint">Loading the timeline…</div>}
        {isError && <div className="flex-1 py-8 text-center text-sm text-red">Couldn&apos;t load this video&apos;s timeline.</div>}
        {!isLoading && !isError && blocks.length === 0 && (
          <div className="flex-1 py-8 text-center text-sm text-faint">No scenes yet — they&apos;ll show up here once the script has some.</div>
        )}

        {!isLoading && !isError && blocks.length > 0 && (
          <div className="flex min-h-0 flex-1">
            {/* Fixed left track-head column — never scrolls horizontally. */}
            <div className="flex w-[76px] flex-none flex-col border-r border-line-soft bg-deep">
              <div className="h-6 flex-none border-b border-line-soft" />
              <div className="flex h-[76px] flex-none items-center px-2 text-[10.5px] text-dim">Video</div>
              <div className="flex h-9 flex-none items-center gap-1 border-t border-line-soft px-2 text-[10.5px] text-dim">
                Voice
              </div>
              <div className="flex h-9 flex-none items-center gap-1 border-t border-line-soft px-2 text-[10.5px] text-dim">
                <Music size={10} className="flex-none text-faint" /> Music
              </div>
            </div>

            {/* Scrollable track content — ruler + video/voice/music lanes,
                all sized from the SAME per-scene segmentWidths map so every
                row lines up in one pass, no coordinate math needed. */}
            <div className="relative flex-1 overflow-x-auto overflow-y-hidden">
              <div className="relative w-max min-w-full">
                {/* Playhead — inert in v1, positioned at the track start per
                    the layout correction's follow-up amendment. No
                    scrubbing, no drag. */}
                <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-[1.5px] bg-red">
                  <div className="absolute -left-[3px] -top-1 h-2.5 w-2.5 rounded-[2px] bg-red" />
                </div>

                <RulerRow blocks={blocks} segmentWidths={segmentWidths} rulerMode={rulerMode} durationForSlot={durationForSlot} />

                <div className="flex h-[76px] items-center gap-1 border-b border-line-soft p-1.5">
                  {blocks.map((block) => (
                    <VideoSegment
                      key={block.scene}
                      block={block}
                      width={segmentWidths.get(block.scene) ?? ORDINAL_EMPTY_W}
                      expanded={expandedScenes.has(block.scene)}
                      onToggle={() => toggleScene(block.scene)}
                    />
                  ))}
                </div>

                <div className="flex h-9 items-center gap-1 border-b border-line-soft p-1.5">
                  {blocks.map((block) => (
                    <NarrationSegment
                      key={block.scene}
                      width={segmentWidths.get(block.scene) ?? ORDINAL_EMPTY_W}
                      scene={scriptByScene.get(block.scene)}
                    />
                  ))}
                </div>

                <div className="flex h-9 items-center p-1.5">
                  <MusicLanePlaceholder width={Array.from(segmentWidths.values()).reduce((a, b) => a + b + CELL_GAP, 0)} />
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ordinalCollapsedWidth(block: TimelineStoryboardBlock): number {
  const n = block.slots.length;
  if (n === 0) return ORDINAL_EMPTY_W;
  return Math.min(ORDINAL_MAX_W, ORDINAL_BASE_W + n * ORDINAL_PER_SHOT_W);
}

/** Estimated pixel width of an expanded segment's in-track run (collapse
 *  tab + regular cells + an overflow divider/cells when present). Used only
 *  for the ruler's sequence-marker/real-tick alignment — the video lane
 *  itself doesn't need this number since normal flex flow sizes it exactly;
 *  a few px of drift here in real-duration mode (untestable with today's
 *  real data — see file header) is a cosmetic v1 tolerance, not a
 *  correctness issue, since nothing here is scrubbable. */
function expandedRunWidth(block: TimelineStoryboardBlock): number {
  const regular = block.slots.filter((s) => s.board !== null).length;
  const overflow = block.slots.filter((s) => s.board === null).length;
  let w = COLLAPSE_TAB_W + CELL_GAP + regular * (CELL + CELL_GAP);
  if (overflow > 0) w += OVERFLOW_DIVIDER_W + CELL_GAP + overflow * (CELL + CELL_GAP);
  return w;
}

/** Ruler row — real proportional ticks when `rulerMode === "real"`
 *  (unreachable with today's live data, see file header), sequence markers
 *  ("Scene N") otherwise. Built from the SAME per-scene `segmentWidths` the
 *  lanes below use, as one more per-scene cell in the same flex row, so
 *  alignment is exact by construction rather than computed twice. */
function RulerRow({
  blocks,
  segmentWidths,
  rulerMode,
  durationForSlot,
}: {
  blocks: TimelineStoryboardBlock[];
  segmentWidths: Map<number, number>;
  rulerMode: "real" | "sequence";
  durationForSlot: (slot: TimelineSlot) => number | null;
}) {
  const totalSeconds = useMemo(() => {
    if (rulerMode !== "real") return 0;
    let total = 0;
    for (const b of blocks) for (const s of b.slots) total += durationForSlot(s) ?? 0;
    return total;
  }, [blocks, rulerMode, durationForSlot]);
  const interval = tickIntervalSeconds(totalSeconds);

  let cumulativeSeconds = 0;

  return (
    <div className="flex h-6 items-stretch gap-1 border-b border-line-soft bg-deep px-1.5">
      {blocks.map((block) => {
        const width = segmentWidths.get(block.scene) ?? ORDINAL_EMPTY_W;

        if (rulerMode === "sequence") {
          return (
            <div key={block.scene} className="flex flex-none items-center justify-start" style={{ width }}>
              <span className="truncate text-[9.5px] text-faint">Scene {block.scene}</span>
            </div>
          );
        }

        const sceneStart = cumulativeSeconds;
        const sceneDuration = block.slots.reduce((sum, s) => sum + (durationForSlot(s) ?? 0), 0);
        cumulativeSeconds += sceneDuration;

        const ticks: { offsetPx: number; label: string }[] = [];
        let t = Math.ceil(sceneStart / interval) * interval;
        // A t===0 tick only belongs to the FIRST scene (avoid double-drawing
        // "0:00" if a later scene's start also lands exactly on an interval).
        if (t === 0 && block.scene !== blocks[0]?.scene) t += interval;
        for (; t < sceneStart + sceneDuration + 0.001; t += interval) {
          const frac = sceneDuration > 0 ? (t - sceneStart) / sceneDuration : 0;
          ticks.push({ offsetPx: frac * width, label: formatMMSS(t) });
        }

        return (
          <div key={block.scene} className="relative flex-none" style={{ width }}>
            {ticks.map((tick, i) => (
              <span
                key={i}
                className="absolute top-1 whitespace-nowrap text-[9px] text-faint"
                style={{ left: `${tick.offsetPx}px` }}
              >
                {tick.label}
              </span>
            ))}
          </div>
        );
      })}
    </div>
  );
}

/** One video-track segment — collapsed shows the scene's storyboard sheets
 *  as its face (a real editor-style clip thumbnail), "Storyboard N" as its
 *  label. Clicking it expands IN PLACE into its slot cells side by side on
 *  the SAME track (siblings shift right via normal flex flow) — never a
 *  vertical card or tray, per the layout correction's follow-up amendment:
 *  that read as the Scene view again, which is exactly what got rejected. */
function VideoSegment({
  block,
  width,
  expanded,
  onToggle,
}: {
  block: TimelineStoryboardBlock;
  width: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  const canExpand = block.expanded;
  const sheetUrls = block.boardUrls.filter((u): u is string => Boolean(u));
  const hasSheets = sheetUrls.length > 0;

  if (expanded && canExpand) {
    const regularSlots = block.slots.filter((s) => s.board !== null);
    const overflowSlots = block.slots.filter((s) => s.board === null);
    return (
      <div className="flex h-16 flex-none items-stretch gap-1">
        <button
          type="button"
          onClick={onToggle}
          title={`Collapse Storyboard ${block.scene}`}
          className="flex w-7 flex-none flex-col items-center justify-center gap-0.5 rounded-[6px] border border-turquoise/35 bg-turquoise/[0.12] text-turquoise"
        >
          <ChevronDown size={11} className="rotate-180" />
          <span className="text-[8px] font-semibold">{block.scene}</span>
        </button>
        {regularSlots.map((slot) => (
          <SlotTile key={slot.panel} slot={slot} />
        ))}
        {overflowSlots.length > 0 && (
          <>
            <div className="flex h-16 w-10 flex-none flex-col items-center justify-center rounded-[7px] border border-dashed border-line-soft bg-deep text-center leading-tight">
              <span className="text-[8px] font-semibold text-faint">+{overflowSlots.length}</span>
              <span className="text-[7px] text-faint">more</span>
            </div>
            {overflowSlots.map((slot) => (
              <SlotTile key={slot.panel} slot={slot} />
            ))}
          </>
        )}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={canExpand ? onToggle : undefined}
      disabled={!canExpand}
      title={canExpand ? `Storyboard ${block.scene} — click to expand` : segmentDisabledReason(hasSheets)}
      style={{ width }}
      className={`relative h-16 flex-none overflow-hidden rounded-[7px] border border-line-soft ${canExpand ? "cursor-pointer hover:border-turquoise/50" : "cursor-default"}`}
    >
      {hasSheets ? (
        <div className="flex h-full w-full">
          {sheetUrls.map((url, i) => (
            <SkeletonThumb
              key={i}
              src={toDisplayImageUrl(url)}
              alt={`Scene ${block.scene} storyboard sheet ${i + 1}`}
              className="h-full min-w-0 flex-1 border-r border-black/30 last:border-r-0"
            />
          ))}
        </div>
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-deep">
          <ImageOff size={14} className="text-faint" />
        </div>
      )}
      <span className="absolute bottom-0.5 left-1 right-1 truncate rounded bg-black/60 px-1 py-[1px] text-left text-[8.5px] font-medium text-white/90 backdrop-blur-sm">
        Storyboard {block.scene}
      </span>
      {block.slots.length > 0 && (
        <span className="absolute top-0.5 right-0.5 rounded bg-black/55 px-1 py-[1px] text-[7.5px] text-white/80">
          {block.slots.length}
        </span>
      )}
    </button>
  );
}

function segmentDisabledReason(hasSheets: boolean): string {
  if (hasSheets) {
    return "This scene's storyboard sheet is drawn, but there's no per-shot breakdown to expand yet.";
  }
  return "Nothing drawn for this scene yet";
}

/** Narration lane cell — one per scene, aligned under its video segment.
 *  Real data (`scripts.voice_over_url`, already fetched via
 *  `["video-script", videoId]`) when it exists; a muted, inert placeholder
 *  otherwise. Never a clickable "Add voiceover" affordance — that's T3+. */
function NarrationSegment({ width, scene }: { width: number; scene: ScriptScene | undefined }) {
  const hasVoice = Boolean(scene?.voice_over_url);
  if (hasVoice) {
    return (
      <div
        title={`Scene ${scene?.scene} narration recorded`}
        style={{ width }}
        className="flex h-7 flex-none items-center gap-1 rounded-[6px] border border-turquoise/32 bg-turquoise/[0.1] px-1.5"
      >
        <div className="h-2.5 flex-1 rounded-full bg-turquoise/25" />
      </div>
    );
  }
  return (
    <div
      title="No narration recorded for this scene yet"
      style={{ width }}
      className="flex h-7 flex-none items-center justify-center rounded-[6px] border border-dashed border-line-soft bg-deep/40"
    >
      <MicOff size={10} className="text-faint/70" />
    </div>
  );
}

/** Music lane — no music data exists anywhere on this surface's queries, so
 *  this is always the muted "nothing here" placeholder, spanning the full
 *  track width. Inert — no "Add music" affordance (T3+). */
function MusicLanePlaceholder({ width }: { width: number }) {
  return (
    <div
      style={{ width }}
      className="flex h-7 flex-none items-center justify-center gap-1.5 rounded-[6px] border border-dashed border-line-soft bg-deep/40"
    >
      <Music size={10} className="text-faint/70" />
      <span className="text-[9.5px] text-faint/70">No music yet</span>
    </div>
  );
}

/** One slot tile — honest per-slot fill state (planned / pending / image /
 *  clip / failed). See timeline-slots.ts's STATE MACHINE section for what
 *  each state actually means and how thin "failed" coverage really is; this
 *  tile never renders a failure badge that implies it fires reliably.
 *  Unchanged from the vertical-card build other than living inline on the
 *  track now instead of in a wrapped grid. */
function SlotTile({ slot }: { slot: TimelineSlot }) {
  const label = `${slot.plan?.role ?? "SHOT"} ${slot.plan?.shotType ?? ""}`.trim();
  const title = slot.plan
    ? `[${slot.panel}] ${label}${slot.plan.speaker ? ` — ${slot.plan.speaker}: "${slot.plan.line}"` : ""}\n${slot.plan.desc}`
    : `Panel ${slot.panel}`;

  if (slot.state === "planned") {
    return (
      <div
        title={title}
        className="flex h-16 w-16 flex-none flex-col items-center justify-center gap-0.5 rounded-[7px] border border-dashed border-line-soft bg-deep/60"
      >
        <span className="text-[9px] text-faint">#{slot.panel}</span>
        <span className="text-[8.5px] text-faint">planned</span>
      </div>
    );
  }

  if (slot.state === "pending") {
    return (
      <div
        title={title}
        className="relative flex h-16 w-16 flex-none flex-col items-center justify-center gap-1 rounded-[7px] border border-line-soft bg-deep"
      >
        <Clock size={13} className="text-faint" />
        <span className="text-[8.5px] text-faint">#{slot.panel}</span>
      </div>
    );
  }

  if (slot.state === "clip") {
    return (
      <div title={title} className="relative h-16 w-16 flex-none overflow-hidden rounded-[7px] border border-turquoise/30">
        <SkeletonThumb src={toDisplayImageUrl(slot.asset?.image_url)} alt={title} className="h-full w-full" />
        <span className="absolute bottom-1 left-1 rounded-md bg-black/60 px-1 py-[1px] text-[8px] font-semibold text-white backdrop-blur-sm">
          <Film size={8} className="mr-0.5 inline" />
          clip
        </span>
        <span className="absolute top-1 right-1 rounded-md bg-black/55 px-1 py-[1px] text-[8px] text-white/85">
          #{slot.panel}
        </span>
      </div>
    );
  }

  if (slot.state === "image") {
    return (
      <div title={title} className="relative h-16 w-16 flex-none overflow-hidden rounded-[7px] border border-line-soft">
        <SkeletonThumb src={toDisplayImageUrl(slot.asset?.image_url)} alt={title} className="h-full w-full" />
        <span className="absolute top-1 right-1 rounded-md bg-black/55 px-1 py-[1px] text-[8px] text-white/85">
          #{slot.panel}
        </span>
      </div>
    );
  }

  // "failed" — implemented defensively and thinly covered on the real write
  // paths (see timeline-slots.ts header). Shown subtly, on purpose: this is
  // NOT a badge that promises to fire reliably for a live animation-channel
  // failure — T1 found the live clip-failure path never persists a marker.
  return (
    <div
      title={`${title}\n(may not have generated — this indicator is not reliable yet)`}
      className="relative flex h-16 w-16 flex-none flex-col items-center justify-center gap-1 rounded-[7px] border border-line-soft bg-deep opacity-70"
    >
      <AlertTriangle size={12} className="text-faint" />
      <span className="text-[8.5px] text-faint">#{slot.panel}</span>
    </div>
  );
}

/** Shared skeleton-then-image treatment for every media tile in this view —
 *  the media proxy (`/api/media/drive`) can take seconds, so every image
 *  here shows a pulse placeholder instead of a layout jump or a blank box.
 *  `src` undefined (no URL at all) renders the same muted "nothing here"
 *  tile SlotTile's planned/pending states already use, never a broken-image
 *  icon.
 *
 *  Found live verifying this chunk against real production data: a stored
 *  storyboard sheet URL can genuinely 404/400 (a stale/deleted object,
 *  confirmed by hand with a plain curl against the real URL — not something
 *  this view caused). The naive version of this component treated
 *  `onError` the same as `onLoad` (just stop showing the skeleton), which
 *  left a broken native `<img>` on screen — browsers render an unstyled
 *  broken-image glyph plus the raw `alt` text with no box constraint, so it
 *  visibly overflowed this tile's tiny footprint into whatever sat next to
 *  it. `errored` tracks that case separately and falls back to the exact
 *  same muted ImageOff tile the "no src at all" branch already uses — a
 *  missing picture and a broken one should look identical to the viewer,
 *  both honestly "nothing to show here." */
function SkeletonThumb({ src, alt, className }: { src: string | undefined; alt: string; className?: string }): ReactNode {
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);
  if (!src || errored) {
    return (
      <div className={`flex items-center justify-center bg-deep ${className ?? ""}`}>
        <ImageOff size={12} className="text-faint" />
      </div>
    );
  }
  return (
    <div className={`relative overflow-hidden bg-deep ${className ?? ""}`}>
      {!loaded && <div className="absolute inset-0 animate-pulse bg-raise" />}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        loading="lazy"
        onLoad={() => setLoaded(true)}
        onError={() => setErrored(true)}
        className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-300 ${loaded ? "opacity-100" : "opacity-0"}`}
      />
    </div>
  );
}
