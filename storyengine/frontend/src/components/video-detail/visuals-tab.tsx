"use client";

import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import {
  getVideoScript,
  getVideoAssets,
  updateStoryboardMode,
  clearAllStoryboards,
  Asset,
} from "@/lib/api";
import { StoryboardViewer } from "./storyboard-viewer";
import { ImageSegmentCard } from "./image-segment-card";
import { VoicePlayer } from "./voice-player";
import { StageAdvancer } from "./stage-advancer";

interface VisualsTabProps {
  videoId: string;
  videoStatus: string;
}

export function VisualsTab({ videoId, videoStatus }: VisualsTabProps) {
  const queryClient = useQueryClient();

  const { data: scenes } = useQuery({
    queryKey: ["video-script", videoId],
    queryFn: () => getVideoScript(videoId),
  });

  const { data: assets, refetch: refetchAssets } = useQuery({
    queryKey: ["video-assets", videoId],
    queryFn: () => getVideoAssets(videoId),
  });

  const storyboardMode =
    scenes?.some((s) => s.storyboard_on_off === "On") ?? false;

  const handleToggleStoryboard = async () => {
    await updateStoryboardMode(videoId, !storyboardMode);
    queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
  };

  const handleClearAll = async () => {
    await clearAllStoryboards(videoId);
    queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
  };

  const anyGridsExist = scenes?.some(
    (s) => s.storyboard_1_url || s.storyboard_2_url || s.storyboard_3_url
  ) ?? false;

  const assetsByScene = useMemo(() => {
    if (!assets) return {};
    const grouped: Record<number, Asset[]> = {};
    for (const a of assets) {
      const s = a.scene ?? 0;
      if (!grouped[s]) grouped[s] = [];
      grouped[s].push(a);
    }
    for (const s of Object.keys(grouped)) {
      grouped[Number(s)].sort(
        (a, b) => (a.image_index ?? 0) - (b.image_index ?? 0)
      );
    }
    return grouped;
  }, [assets]);

  // Determine which StageAdvancer to show
  const advancer = (() => {
    if (storyboardMode) {
      if (videoStatus === "ready_for_storyboards") {
        return { stage: "storyboards", label: "Generate Storyboard Grids" };
      }
      if (videoStatus === "ready_for_storyboard_images") {
        return {
          stage: "storyboard-images",
          label: "Generate Grid Images",
        };
      }
      if (videoStatus === "ready_for_storyboard_extraction") {
        return {
          stage: "storyboard-extract",
          label: "Extract & Upscale Approved",
        };
      }
    } else {
      if (videoStatus === "ready_for_images") {
        return { stage: "images", label: "Generate All Images" };
      }
    }
    if (
      videoStatus === "ready_for_thumbnail" ||
      videoStatus === "images_done"
    ) {
      return { stage: "thumbnail", label: "Advance to Thumbnail" };
    }
    return null;
  })();

  return (
    <div className="space-y-5">
      {/* Header with storyboard toggle */}
      <div className="flex items-center justify-between">
        <h2
          className="text-lg font-semibold"
          style={{ color: "var(--text-primary)" }}
        >
          Visuals
        </h2>
        <div className="flex items-center gap-3">
          {storyboardMode && anyGridsExist && (
            <button
              onClick={handleClearAll}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded transition-opacity"
              style={{ background: "rgba(196, 69, 69, 0.15)", color: "#C44545" }}
              title="Clear all storyboard grids"
            >
              <Trash2 size={10} /> Clear All
            </button>
          )}
          <span
            className="text-xs"
            style={{ color: "var(--text-muted)" }}
          >
            Storyboard
          </span>
          <div
            onClick={handleToggleStoryboard}
            style={{
              width: 40,
              height: 22,
              background: storyboardMode ? "var(--amber)" : "var(--border)",
              borderRadius: 11,
              position: "relative",
              cursor: "pointer",
            }}
          >
            <div
              style={{
                width: 18,
                height: 18,
                background: storyboardMode
                  ? "var(--bg-primary)"
                  : "var(--text-muted)",
                borderRadius: "50%",
                position: "absolute",
                top: 2,
                left: storyboardMode ? undefined : 2,
                right: storyboardMode ? 2 : undefined,
                transition: "all 0.2s",
              }}
            />
          </div>
        </div>
      </div>

      {/* Info banner */}
      {storyboardMode ? (
        <div
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            background: "rgba(245, 158, 11, 0.1)",
            border: "1px solid rgba(245, 158, 11, 0.25)",
            color: "var(--amber)",
          }}
        >
          Storyboard mode: Generate grids, approve panels, then extract
          and upscale selected images.
        </div>
      ) : (
        <div
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
            color: "var(--text-muted)",
          }}
        >
          Direct mode: Images generated individually per segment from
          prompts.
        </div>
      )}

      {/* Stage advancer */}
      {advancer && (
        <StageAdvancer
          videoId={videoId}
          stage={advancer.stage}
          label={advancer.label}
        />
      )}

      {/* Scene cards */}
      {scenes && scenes.length > 0 ? (
        <div className="space-y-6">
          {scenes.map((s) => {
            const sceneNum = s.scene ?? 0;
            const sceneAssets = assetsByScene[sceneNum] ?? [];

            if (storyboardMode) {
              return (
                <StoryboardViewer
                  key={s.id}
                  scene={s}
                  assets={sceneAssets}
                  videoId={videoId}
                  videoStatus={videoStatus}
                  onRefresh={refetchAssets}
                />
              );
            }

            return (
              <div
                key={s.id}
                className="rounded-xl overflow-hidden"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                }}
              >
                {/* Scene header */}
                <div className="flex items-center gap-2 px-4 py-3">
                  <span
                    className="text-xs font-bold px-2 py-0.5 rounded"
                    style={{
                      background: "rgba(26, 138, 122, 0.15)",
                      color: "var(--teal)",
                    }}
                  >
                    Scene {sceneNum}
                  </span>
                </div>

                {/* Voice player */}
                {s.voice_over_url && (
                  <div className="px-4 pb-3">
                    <VoicePlayer audioUrl={s.voice_over_url} />
                  </div>
                )}

                {/* Image segment cards */}
                {sceneAssets.length > 0 ? (
                  <div className="px-4 pb-4 space-y-3">
                    {sceneAssets.map((asset) => (
                      <ImageSegmentCard
                        key={asset.id}
                        asset={asset}
                        videoId={videoId}
                        onRefresh={refetchAssets}
                      />
                    ))}
                  </div>
                ) : (
                  <div
                    className="px-4 pb-4 text-sm"
                    style={{ color: "var(--text-muted)" }}
                  >
                    No images yet for this scene.
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div
          className="text-center py-12"
          style={{ color: "var(--text-muted)" }}
        >
          No scenes found. Script must be generated first.
        </div>
      )}
    </div>
  );
}
