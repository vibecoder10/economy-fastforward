"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Clock, Film, ImageOff, AlertTriangle } from "lucide-react";
import { getVideoAssets, getVideoScript } from "@/lib/api";
import { toDisplayImageUrl } from "@/lib/utils";
import { buildTimelineSlots, type TimelineSlot, type TimelineStoryboardBlock } from "@/components/canvas-shared/timeline-slots";
import { CanvasEmptyState } from "./CanvasEmptyState";

/**
 * Timeline altitude (Chunk T2) — replaces the static
 * `TimelineAltitudePlaceholder` mock that used to live in CanvasStage.tsx.
 * Real data, read-only. See TIMELINE-WORKBENCH-PLAN.md for the mission and
 * the three locked decisions this view must hold to:
 *
 *   1. Ordinal lanes, no time ruler, no seconds anywhere. One lane per
 *      scene, blocks in scene order — never sized or positioned by a
 *      real/implied duration (durations don't exist pre-clip, see the
 *      plan's constraint #2).
 *   2. "Storyboard N" = scene N. A scene can span up to 5 board sheets
 *      internally — still rendered as ONE block.
 *   3. Zero spend, zero generate/animate/approve affordances. That's T3+.
 *
 * Data comes from the SAME two React Query caches SceneAltitudeView.tsx and
 * RightRail.tsx already populate on this surface (`["video-script", videoId]`,
 * `["video-assets", videoId]`) — no new endpoint. `buildTimelineSlots`
 * (canvas-shared/timeline-slots.ts, T1) turns those two arrays into the
 * per-scene block + slot list this view renders; read that file's header
 * before changing the slot logic — it documents the parser verdict, the
 * overflow-slot decision, and exactly how honest "failed" is allowed to be.
 */
export function TimelineAltitudeView({ videoId }: { videoId: string }) {
  const scriptQuery = useQuery({
    queryKey: ["video-script", videoId],
    queryFn: () => getVideoScript(videoId),
  });
  const assetsQuery = useQuery({
    queryKey: ["video-assets", videoId],
    queryFn: () => getVideoAssets(videoId),
  });

  const blocks = useMemo(
    () => buildTimelineSlots(scriptQuery.data ?? [], assetsQuery.data ?? []),
    [scriptQuery.data, assetsQuery.data],
  );

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

  const isLoading = scriptQuery.isLoading || assetsQuery.isLoading;
  const isError = scriptQuery.isError || assetsQuery.isError;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header bar — mirrors SceneAltitudeView's 50px stage bar so the two
          altitudes read as one family, but the copy here is honest about
          what changed: ordinal order, no time ruler (locked decisions #1/#2
          above), not a caption borrowed from the old placeholder's fake
          timecode. */}
      <div className="flex h-[50px] flex-none items-center gap-2.5 border-b border-line-soft px-5">
        <span className="text-[13px] font-semibold text-ink">Timeline</span>
        <span className="text-[11.5px] text-faint">
          One lane per scene, in scene order — no time ruler yet
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-5 pb-[60px] pt-4.5">
        {isLoading && <div className="py-10 text-center text-sm text-faint">Loading the timeline…</div>}
        {isError && (
          <div className="py-10 text-center text-sm text-red">Couldn&apos;t load this video&apos;s timeline.</div>
        )}
        {!isLoading && !isError && blocks.length === 0 && (
          <div className="h-full min-h-[320px]">
            <CanvasEmptyState />
          </div>
        )}

        {!isLoading &&
          !isError &&
          blocks.map((block) => (
            <SceneLane
              key={block.scene}
              block={block}
              expanded={expandedScenes.has(block.scene)}
              onToggle={() => toggleScene(block.scene)}
            />
          ))}
      </div>
    </div>
  );
}

/** One lane = one scene = one "Storyboard N" block, per the locked
 *  vocabulary decision (TIMELINE-WORKBENCH-PLAN.md's "Storyboard N = scene
 *  N"). A scene with no storyboard sheets yet still gets a lane — an honest
 *  empty block, not a hidden row — so a brand-new video's timeline reads as
 *  "here's where every scene will show up," matching the D3-29 lesson this
 *  chunk brief calls out (this view must handle every real shape). */
function SceneLane({
  block,
  expanded,
  onToggle,
}: {
  block: TimelineStoryboardBlock;
  expanded: boolean;
  onToggle: () => void;
}) {
  const canExpand = block.expanded; // block.expanded === "has at least one real slot"
  const sheetUrls = block.boardUrls.filter((u): u is string => Boolean(u));
  const hasSheets = sheetUrls.length > 0;
  const regularSlots = block.slots.filter((s) => s.board !== null);
  const overflowSlots = block.slots.filter((s) => s.board === null);

  return (
    <div className="mb-3 rounded-card border border-line-soft bg-surface">
      <button
        type="button"
        onClick={canExpand ? onToggle : undefined}
        disabled={!canExpand}
        title={canExpand ? undefined : laneDisabledReason(hasSheets)}
        className={`flex w-full items-center gap-3 px-3.5 py-3 text-left ${canExpand ? "cursor-pointer" : "cursor-default"}`}
      >
        <div className="flex h-8 w-8 flex-none items-center justify-center rounded-card-sm text-dim">
          {canExpand ? (
            <ChevronDown size={15} className={expanded ? "transition-transform" : "-rotate-90 transition-transform"} />
          ) : (
            <span className="h-1.5 w-1.5 rounded-full bg-line-soft" />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-medium leading-snug text-ink">
            <span className="mr-1 text-turquoise">Storyboard {block.scene}</span>
          </div>
          <div className="mt-0.5 text-[11px] text-faint">{laneSubtitle(block, hasSheets)}</div>
        </div>

        {/* Block face: the scene's storyboard sheet(s) — a multi-sheet scene
            still renders as one filmstrip inside one block, per the locked
            "one scene, one storyboard block" decision. */}
        <div className="flex flex-none items-center gap-1">
          {hasSheets ? (
            sheetUrls.slice(0, 5).map((url, i) => (
              <SkeletonThumb
                key={i}
                src={toDisplayImageUrl(url)}
                alt={`Scene ${block.scene} storyboard sheet ${i + 1}`}
                className="h-11 w-[70px] flex-none rounded-[6px] border border-line-soft"
              />
            ))
          ) : (
            <div className="flex h-11 w-[70px] flex-none items-center justify-center rounded-[6px] border border-dashed border-line-soft bg-deep">
              <ImageOff size={13} className="text-faint" />
            </div>
          )}
        </div>
      </button>

      {expanded && canExpand && (
        <div className="border-t border-line-soft px-3.5 py-3">
          {regularSlots.length === 0 && overflowSlots.length === 0 ? (
            <p className="py-2 text-[11.5px] text-faint">No shots yet for this scene.</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                {regularSlots.map((slot) => (
                  <SlotTile key={slot.panel} slot={slot} />
                ))}
              </div>
              {overflowSlots.length > 0 && (
                <div className="mt-3 border-t border-line-soft pt-3">
                  <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-wide text-faint">
                    +{overflowSlots.length} more shot{overflowSlots.length === 1 ? "" : "s"} — past the storyboard sheets
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {overflowSlots.map((slot) => (
                      <SlotTile key={slot.panel} slot={slot} />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** Lane subtitle — a short, honest read of where this scene stands.
 *  Deliberately never mentions time/seconds (locked decision #1).
 *
 *  `hasSheets` (real storyboard_N_url images) and `block.expanded` (real
 *  parseable slots) are genuinely independent facts — found live verifying
 *  this chunk: a real production video had drawn sheets for every scene
 *  (visible thumbnails) whose `storyboard_prompts` text was a prose
 *  grid-layout description rather than the `[k] M... —` BEAT-panel format
 *  `parseEnforcedPlan` (canvas-shared/shot-plan-parsers.ts) requires, so it
 *  correctly parses to zero slots (T1's documented, defensive behavior —
 *  not a bug). Saying "Not drawn yet" next to a visible sheet thumbnail
 *  would have been a lie the block face right next to it disproves on
 *  sight — this distinguishes the two instead. */
function laneSubtitle(block: TimelineStoryboardBlock, hasSheets: boolean): string {
  if (!block.expanded) return hasSheets ? "Drawn — no shot breakdown available" : "Not drawn yet";
  const total = block.slots.length;
  const filled = block.slots.filter((s) => s.state === "image" || s.state === "clip").length;
  const clips = block.slots.filter((s) => s.state === "clip").length;
  if (clips === total && total > 0) return `${total} shot${total === 1 ? "" : "s"} · all clips`;
  if (filled === 0) return `${total} shot${total === 1 ? "" : "s"} planned`;
  return `${filled}/${total} shot${total === 1 ? "" : "s"} filled`;
}

/** Tooltip for a disabled (non-expandable) lane — same honesty split as
 *  laneSubtitle above, just longer-form since it's a hover title. */
function laneDisabledReason(hasSheets: boolean): string {
  if (hasSheets) {
    return "This scene's storyboard sheet is drawn, but there's no per-shot breakdown to expand yet.";
  }
  return "Nothing drawn for this scene yet";
}

/** One slot tile — honest per-slot fill state (planned / pending / image /
 *  clip / failed). See timeline-slots.ts's STATE MACHINE section for what
 *  each state actually means and how thin "failed" coverage really is; this
 *  tile never renders a failure badge that implies it fires reliably. */
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
 *  visibly overflowed this tile's tiny 44-70px footprint into whatever sat
 *  next to it. `errored` tracks that case separately and falls back to the
 *  exact same muted ImageOff tile the "no src at all" branch already uses —
 *  a missing picture and a broken one should look identical to the viewer,
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
