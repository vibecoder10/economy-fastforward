"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Star } from "lucide-react";
import {
  getVideoAssets,
  getVideoScript,
  getVideo,
  getModels,
  getVideoActions,
  updateAssetModelOverride,
  type Asset,
  type VideoModelInfo,
} from "@/lib/api";
import { clipCost } from "@/lib/next-action";
import { ShotCard } from "@/components/canvas-shared/ShotCard";
import { ModelOverrideSheet } from "@/components/canvas-shared/ModelOverrideSheet";
import { SaveStyleModal } from "./SaveStyleModal";
import { CanvasEmptyState } from "./CanvasEmptyState";
import { useDirector } from "./DirectorContext";

/** Network-failure safety net ONLY, same list ScenesWorkspaceTab.tsx keeps
 * (FALLBACK_WIRED_MODELS there) — if GET /api/models can't be reached, the
 * override sheet still needs something selectable instead of rendering
 * empty. $0.09 = grok-imagine's 6s tier (channel_profile.py, C09a); keep in
 * sync by hand if that price ever moves. */
const FALLBACK_WIRED_MODELS: { id: string; label: string }[] = [
  { id: "grok-imagine", label: "Grok Imagine — $0.09/clip" },
];

/**
 * Scene altitude (default tab) — the stage bar (gold "Lock this as a style"
 * button + helper copy) plus the scene/shot list structure from
 * storyengine/tasks/director-mockup/index.html `#tab-scene` (~L897-1073).
 *
 * Shots render via the shared `ShotCard` (canvas-shared/ShotCard.tsx) — the
 * same component ScenesWorkspaceTab.tsx's pipeline page uses — instead of a
 * bespoke thumbnail tile, so this view gets the real model badge, a price,
 * and a tap-to-focus affordance for free.
 *
 * VIEW + MODEL CHANGE ONLY, on purpose (see the redraw decision this chunk
 * shipped under): `canAnimate={false}` and `readOnly` hide/disable every
 * money-triggering or destructive action ShotCard normally offers (animate,
 * redo clip, delete, re-crop, redraw-picture) — this board never starts
 * work, so it never needs a task-watcher to poll it. Every in-flight state
 * prop below (`isGenerating`, `isQueued`, etc.) is honestly `false`: nothing
 * can ever be mid-flight for a card the board itself can't put into flight.
 * The one live write this view makes is the free one — `assets.model_override`
 * via the existing `ModelOverrideSheet` + `updateAssetModelOverride`.
 */
export function SceneAltitudeView({ videoId }: { videoId: string }) {
  const queryClient = useQueryClient();
  const { setFocusedShotId, setAltitude } = useDirector();

  const assetsQuery = useQuery({
    queryKey: ["video-assets", videoId],
    queryFn: () => getVideoAssets(videoId),
  });
  const scriptQuery = useQuery({
    queryKey: ["video-script", videoId],
    queryFn: () => getVideoScript(videoId),
  });
  // Only field this view needs off the video row is video_model — ShotCard's
  // `effectiveModelId` fallback when a shot has no clip yet and no per-scene
  // routing/override (ShotCard.tsx ~L78-80). Same ["video", videoId] key the
  // rest of the app uses (ScenesWorkspaceTab, the pipeline page), so this is
  // served off the shared cache rather than firing a second request.
  const videoQuery = useQuery({
    queryKey: ["video", videoId],
    queryFn: () => getVideo(videoId),
  });
  // Clip-model registry (name + $/clip) — same ["models"] key
  // ScenesWorkspaceTab.tsx uses, shared cache.
  const modelsQuery = useQuery({
    queryKey: ["models"],
    queryFn: getModels,
    staleTime: 5 * 60_000,
  });
  // Picture price (flat $0.05 today, see docs/cost-awareness.md) — same
  // ["video-actions", videoId] key ScenesWorkspaceTab.tsx reads.
  const videoActionsQuery = useQuery({
    queryKey: ["video-actions", videoId],
    queryFn: () => getVideoActions(videoId),
    staleTime: 30_000,
  });

  const videoDefaultModel = videoQuery.data?.video_model || "grok-imagine";
  const picturePrice = videoActionsQuery.data?.prices?.picture ?? 0.05;

  const priceByModel = useMemo(() => {
    const m: Record<string, number> = {};
    for (const mm of modelsQuery.data?.models ?? []) {
      if (mm.cost_per_clip != null) m[mm.id] = mm.cost_per_clip;
    }
    return m;
  }, [modelsQuery.data]);
  /** Real per-clip price for a model — F6: `prices.clip[model]`/`cost_per_clip`
   * is the model's cheapest-duration-tier price, a flat number, not a
   * per-second rate. Falls back to the shared clipCost() cache (same one
   * ScenesWorkspaceTab.tsx syncs) so a still-loading models query never
   * shows $0.00. */
  const priceForModel = useCallback(
    (id: string | null | undefined) => priceByModel[id || "grok-imagine"] ?? clipCost(id, 1),
    [priceByModel],
  );
  const perClip = priceForModel(videoDefaultModel);

  const modelDisplayName = useCallback(
    (id: string | null | undefined) => {
      if (!id) return "";
      return (modelsQuery.data?.models ?? []).find((m) => m.id === id)?.name ?? id;
    },
    [modelsQuery.data],
  );

  const wiredModelsForSheet = useMemo((): { id: string; label: string }[] => {
    const wired = (modelsQuery.data?.models ?? []).filter((m: VideoModelInfo) => m.kind === "video" && m.wired);
    if (!wired.length) return FALLBACK_WIRED_MODELS;
    return wired.map((m) => ({
      id: m.id,
      label: `${m.name} — $${(m.cost_per_clip ?? priceForModel(m.id)).toFixed(2)}/clip`,
    }));
  }, [modelsQuery.data, priceForModel]);

  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [styleModalOpen, setStyleModalOpen] = useState(false);
  const [overrideAssetId, setOverrideAssetId] = useState<string | null>(null);
  const [savingOverride, setSavingOverride] = useState(false);

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

  // Seed the collapse default ONCE the real scene list arrives — scenes load
  // async off a useQuery, so a plain useState(new Set()) initializer would
  // never see them (they don't exist yet on mount). Collapse every scene
  // past the first three BY ORDER in the sorted `scenes` array above, not by
  // raw scene number (numbers aren't guaranteed contiguous — a 1,2,4,5 list
  // still collapses starting at its 4th entry). The ref guard fires this
  // exactly once per mount so a scene the user manually expands or
  // re-collapses afterward is never stomped back to this default.
  const collapseSeededRef = useRef(false);
  useEffect(() => {
    if (collapseSeededRef.current || scenes.length === 0) return;
    collapseSeededRef.current = true;
    setCollapsed(new Set(scenes.slice(3).map(([sceneNum]) => sceneNum)));
  }, [scenes]);

  const sceneText = (n: number) => scriptQuery.data?.find((s) => s.scene === n)?.scene_text || null;

  const toggleScene = (n: number) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(n)) next.delete(n);
      else next.add(n);
      return next;
    });
  };

  const allAssets = assetsQuery.data ?? [];
  const overrideAsset = overrideAssetId ? allAssets.find((a) => a.id === overrideAssetId) ?? null : null;

  // C14 model override, board flavor of ScenesWorkspaceTab.tsx's
  // handleSetModelOverride — fixed to invalidate BOTH video-assets (the
  // badge) and video-actions (the price/summary), which that one was
  // missing (see the fix left in ScenesWorkspaceTab.tsx alongside this).
  const handleSetModelOverride = useCallback(
    async (assetId: string, next: string | null) => {
      setSavingOverride(true);
      try {
        await updateAssetModelOverride(assetId, next);
        queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
        queryClient.invalidateQueries({ queryKey: ["video-actions", videoId] });
        setOverrideAssetId(null);
      } finally {
        setSavingOverride(false);
      }
    },
    [queryClient, videoId],
  );

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
                <div className="grid grid-cols-1 gap-2.5 px-3.5 pb-3.5 sm:grid-cols-2 xl:grid-cols-3">
                  {assets.map((asset) => (
                    <ShotCard
                      key={asset.id}
                      asset={asset}
                      // Dialogue-speaker lookup isn't fetched by this view
                      // (out of scope for this chunk) — null just omits the
                      // speaker chip, it doesn't fake one.
                      speaker={null}
                      perClip={perClip}
                      picturePrice={picturePrice}
                      canAnimate={false}
                      showModelBadge
                      priceForModel={priceForModel}
                      readOnly
                      isGenerating={false}
                      isRecropping={false}
                      isFailed={false}
                      isQueued={false}
                      isRedrawing={false}
                      isRedrawQueued={false}
                      isRedrawFailed={false}
                      isPlaying={false}
                      disabled={false}
                      videoDefaultModel={videoDefaultModel}
                      modelDisplayName={modelDisplayName}
                      onTap={() => {
                        setFocusedShotId(asset.id);
                        setAltitude("shot");
                      }}
                      // readOnly hides every button below in the UI itself, so
                      // these callbacks are unreachable dead code, not silent
                      // no-ops standing behind a live control.
                      onRedoClip={() => {}}
                      onDeleteClip={() => {}}
                      onDeletePicture={() => {}}
                      onRecrop={() => {}}
                      onRedraw={() => {}}
                      onOpenModelOverride={() => setOverrideAssetId(asset.id)}
                      cameraPresets={[]}
                      onOpenCameraPreset={() => {}}
                    />
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

      {overrideAsset && (
        <ModelOverrideSheet
          asset={overrideAsset}
          models={wiredModelsForSheet}
          videoDefaultModel={videoDefaultModel}
          saving={savingOverride}
          onPick={(id) => handleSetModelOverride(overrideAsset.id, id)}
          onUseRecommendation={() => handleSetModelOverride(overrideAsset.id, null)}
          onClose={() => setOverrideAssetId(null)}
        />
      )}
    </div>
  );
}
