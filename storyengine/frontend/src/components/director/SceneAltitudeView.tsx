"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Star } from "lucide-react";
import { getVideoAssets, getVideoScript, type Asset } from "@/lib/api";
import { toDisplayImageUrl } from "@/lib/utils";
import { SaveStyleModal } from "./SaveStyleModal";
import { CanvasEmptyState } from "./CanvasEmptyState";

/**
 * Scene altitude (default tab) — the stage bar (gold "Lock this as a style"
 * button + helper copy) plus the scene/shot list structure from
 * storyengine/tasks/director-mockup/index.html `#tab-scene` (~L897-1073).
 *
 * Shot badge derivation (LIVE data, no per-shot "storyboard" field exists on
 * `Asset` — this is the closest honest read of the real columns):
 *   video_clip_url set        -> "Clip"
 *   image_url set, no clip    -> "Picture"
 *   image_prompt set, no url  -> "Storyboard" (planned, not drawn yet)
 *   none of the above         -> "Empty"
 *
 * Per-shot model chips (mockup's `.chip`, clickable to open a model picker)
 * are intentionally NOT reproduced here — that's an editing affordance
 * (ModelOverrideSheet already exists in canvas-shared/ for it) out of scope
 * for this chunk's header/rail/gold-button brief, and wiring it risks an
 * accidental paid click during verification. Scene-level per-scene cost
 * pills from the mockup are also omitted — the ledger this app has is a
 * by-stage total, not a by-scene breakdown, and inventing one would violate
 * "never fake data that looks real."
 */
export function SceneAltitudeView({ videoId }: { videoId: string }) {
  const assetsQuery = useQuery({
    queryKey: ["video-assets", videoId],
    queryFn: () => getVideoAssets(videoId),
  });
  const scriptQuery = useQuery({
    queryKey: ["video-script", videoId],
    queryFn: () => getVideoScript(videoId),
  });

  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [styleModalOpen, setStyleModalOpen] = useState(false);

  const scenes = useMemo(() => {
    const byScene = new Map<number, Asset[]>();
    for (const asset of assetsQuery.data ?? []) {
      const n = asset.scene ?? 0;
      if (!byScene.has(n)) byScene.set(n, []);
      byScene.get(n)!.push(asset);
    }
    for (const list of byScene.values()) {
      list.sort((a, b) => (a.image_index ?? 0) - (b.image_index ?? 0));
    }
    return Array.from(byScene.entries()).sort((a, b) => a[0] - b[0]);
  }, [assetsQuery.data]);

  const sceneText = (n: number) => scriptQuery.data?.find((s) => s.scene === n)?.scene_text || null;

  const toggleScene = (n: number) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(n)) next.delete(n);
      else next.add(n);
      return next;
    });
  };

  const isLoading = assetsQuery.isLoading || scriptQuery.isLoading;
  const isError = assetsQuery.isError;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* stage bar */}
      <div className="flex h-[50px] flex-none items-center gap-2.5 border-b border-line-soft px-5">
        <button
          type="button"
          onClick={() => setStyleModalOpen(true)}
          className="inline-flex h-8 items-center gap-1.5 rounded-[9px] border border-gold-director/45 bg-gold-director/[0.08] px-3.5 text-[13px] font-semibold text-gold-director transition-colors hover:border-gold-director/70 hover:bg-gold-director/[0.16]"
        >
          <Star size={13} fill="currentColor" /> Lock this as a style
        </button>
        <span className="text-[11.5px] text-faint">Freezes this look so you can start a new video from it</span>
        <div className="ml-auto flex items-center gap-2 text-[12.5px] text-dim">
          Scene Grouping
          <span
            aria-hidden="true"
            className="relative h-[19px] w-[34px] flex-none rounded-full"
            style={{ background: "rgba(0,212,170,.3)" }}
          >
            <span className="absolute left-[17px] top-[2px] h-[15px] w-[15px] rounded-full bg-turquoise" />
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 pb-[60px] pt-4.5">
        {isLoading && <div className="py-10 text-center text-sm text-faint">Loading scenes…</div>}
        {isError && (
          <div className="py-10 text-center text-sm text-red">
            Couldn&apos;t load this video&apos;s scenes.
          </div>
        )}
        {!isLoading && !isError && scenes.length === 0 && (
          <div className="h-full min-h-[320px]">
            <CanvasEmptyState />
          </div>
        )}

        {scenes.map(([sceneNum, assets]) => {
          const isClosed = collapsed.has(sceneNum);
          const text = sceneText(sceneNum);
          return (
            <div key={sceneNum} className="mb-3.5 rounded-card border border-line-soft bg-surface">
              <div className="flex items-center gap-2.5 px-3.5 py-3">
                <button
                  type="button"
                  onClick={() => toggleScene(sceneNum)}
                  className="flex h-8 w-8 flex-none items-center justify-center rounded-card-sm text-dim hover:bg-raise hover:text-ink"
                >
                  <ChevronDown size={15} className={isClosed ? "-rotate-90 transition-transform" : "transition-transform"} />
                </button>
                <div className="min-w-0 flex-1 text-[13.5px] font-medium leading-snug text-ink">
                  <b className="mr-1 text-turquoise">{sceneNum}.</b>
                  {text ? (text.length > 140 ? `${text.slice(0, 140)}…` : text) : "Untitled scene"}
                </div>
                <div className="flex flex-none items-center gap-2">
                  <span className="flex h-7 items-center rounded-full border border-line-soft bg-deep px-2.5 text-xs text-dim">
                    {assets.length} shot{assets.length === 1 ? "" : "s"}
                  </span>
                </div>
              </div>

              {!isClosed && (
                <div className="flex gap-2.5 overflow-x-auto px-3.5 pb-3.5">
                  {assets.map((asset) => (
                    <ShotTile key={asset.id} asset={asset} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Mockup prefills the field with an example ("Grey Room — cold doc");
          we don't have a real video title threaded down to this component
          without extra prop plumbing, so a generic default is used instead
          (the field is fully editable before saving). */}
      <SaveStyleModal
        open={styleModalOpen}
        defaultName="Untitled style"
        onClose={() => setStyleModalOpen(false)}
      />
    </div>
  );
}

function ShotTile({ asset }: { asset: Asset }) {
  const hasClip = Boolean(asset.video_clip_url);
  const hasPicture = Boolean(asset.image_url) && !hasClip;
  const isPlanned = !hasClip && !hasPicture && Boolean(asset.image_prompt);
  const badge = hasClip ? "Clip" : hasPicture ? "Picture" : isPlanned ? "Storyboard" : "Empty";
  const badgeColor = hasClip ? "text-gold-director" : hasPicture ? "text-turquoise" : "text-faint";
  const thumb = toDisplayImageUrl(asset.image_url);

  return (
    <div className="w-[172px] flex-none overflow-hidden rounded-[13px] border border-line-soft bg-deep transition-colors hover:border-turquoise/35">
      <div className="relative flex h-24 items-center justify-center bg-deep">
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumb} alt="" className="absolute inset-0 h-full w-full object-cover" />
        ) : (
          <div
            aria-hidden="true"
            className="absolute inset-0"
            style={{
              background:
                "repeating-linear-gradient(45deg, rgba(255,255,255,.035) 0 8px, transparent 8px 16px), #0C1018",
            }}
          />
        )}
        <span
          className={`absolute left-1.5 top-1.5 rounded-[6px] bg-black/70 px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-wide backdrop-blur-sm ${badgeColor}`}
        >
          {badge}
        </span>
        {hasClip && asset.duration_seconds ? (
          <span className="absolute bottom-1.5 right-1.5 rounded-[5px] bg-black/70 px-1.5 py-0.5 text-[10px] font-semibold text-white">
            {Math.round(asset.duration_seconds)}s
          </span>
        ) : null}
      </div>
      <div className="p-2.5">
        <p className="line-clamp-2 h-8 text-[11.5px] leading-tight text-dim">
          {asset.sentence_text || asset.image_prompt || "—"}
        </p>
      </div>
    </div>
  );
}
