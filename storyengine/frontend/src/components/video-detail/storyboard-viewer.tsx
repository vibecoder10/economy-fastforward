"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { Check, X, Loader2, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ScriptScene,
  Asset,
  approveAsset,
  rejectAsset,
  runPipelineStage,
  clearSceneStoryboard,
} from "@/lib/api";
import { humanizeError } from "@/lib/errors";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { VoicePlayer } from "./voice-player";
import { PanelMagnifier } from "./panel-magnifier";
import { PromptExpander } from "./prompt-expander";

interface StoryboardViewerProps {
  scene: ScriptScene;
  assets: Asset[];
  videoId: string;
  videoStatus: string;
  onRefresh: () => void;
}

function panelToGrid(panelNum: number): { gridIndex: number; panelInGrid: number } {
  return { gridIndex: Math.floor(panelNum / 9), panelInGrid: panelNum % 9 };
}

export function StoryboardViewer({ scene, assets, videoId, videoStatus, onRefresh }: StoryboardViewerProps) {
  const [selectedPanel, setSelectedPanel] = useState<number | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [sceneTaskRunning, setSceneTaskRunning] = useState(false);
  const [sceneTaskType, setSceneTaskType] = useState<"prompts" | "images" | null>(null);
  const [sceneResult, setSceneResult] = useState<"success" | "error" | null>(null);
  const [sceneError, setSceneError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const gridUrls = [
    scene.storyboard_1_url,
    scene.storyboard_2_url,
    scene.storyboard_3_url,
  ].filter((url): url is string => url != null);

  const totalPanels = gridUrls.length * 9;
  const approvedCount = assets.filter((a) => a.status === "approved").length;
  const sceneNum = scene.scene ?? 0;
  const actNum = Math.ceil(sceneNum / 4) || 1;

  const hasPrompts = !!scene.storyboard_prompts;
  const hasGrids = gridUrls.length > 0;
  const storyboardStatus = scene.storyboard_status;

  // Build a map from image_index to asset for quick lookup
  const assetByIndex = new Map<number, Asset>();
  for (const asset of assets) {
    if (asset.image_index != null) {
      assetByIndex.set(asset.image_index, asset);
    }
  }

  // Task poller for per-scene operations
  const { message: taskMessage } = useTaskPoller({
    videoId,
    enabled: sceneTaskRunning,
    onComplete: () => {
      setSceneTaskRunning(false);
      setSceneTaskType(null);
      setSceneResult("success");
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      onRefresh();
      setTimeout(() => setSceneResult(null), 3000);
    },
    onFailed: (err) => {
      setSceneTaskRunning(false);
      setSceneTaskType(null);
      setSceneResult("error");
      setSceneError(err);
    },
  });

  const handleGeneratePrompts = useCallback(async () => {
    setSceneResult(null);
    setSceneError(null);
    try {
      await runPipelineStage(videoId, "storyboards", { scene: sceneNum });
      setSceneTaskRunning(true);
      setSceneTaskType("prompts");
    } catch (err: any) {
      setSceneResult("error");
      setSceneError(humanizeError(err, "We couldn't start prompt generation. Try again."));
    }
  }, [videoId, sceneNum]);

  const handleGenerateImages = useCallback(async () => {
    setSceneResult(null);
    setSceneError(null);
    try {
      await runPipelineStage(videoId, "storyboard-images", { scene: sceneNum });
      setSceneTaskRunning(true);
      setSceneTaskType("images");
    } catch (err: any) {
      setSceneResult("error");
      setSceneError(humanizeError(err, "We couldn't start image generation. Try again."));
    }
  }, [videoId, sceneNum]);

  const handleClearScene = useCallback(async () => {
    try {
      await clearSceneStoryboard(videoId, sceneNum);
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
      onRefresh();
    } catch (err: any) {
      setSceneResult("error");
      setSceneError(humanizeError(err, "We couldn't clear this scene. Try again."));
    }
  }, [videoId, sceneNum, queryClient, onRefresh]);

  const getAssetForPanel = useCallback(
    (panelNum: number): Asset | undefined => {
      return assetByIndex.get(panelNum + 1);
    },
    [assetByIndex]
  );

  const getStatusForPanel = (panelNum: number): "approved" | "rejected" | "pending" => {
    const asset = getAssetForPanel(panelNum);
    if (!asset) return "pending";
    if (asset.status === "approved") return "approved";
    if (asset.status === "rejected") return "rejected";
    return "pending";
  };

  const handleApprove = async () => {
    if (selectedPanel == null) return;
    const asset = getAssetForPanel(selectedPanel);
    if (!asset) return;
    setActionLoading(true);
    try {
      await approveAsset(asset.id);
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
      onRefresh();
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async () => {
    if (selectedPanel == null) return;
    const asset = getAssetForPanel(selectedPanel);
    if (!asset) return;
    setActionLoading(true);
    try {
      await rejectAsset(asset.id);
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
      onRefresh();
    } finally {
      setActionLoading(false);
    }
  };

  // Keyboard navigation
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (totalPanels === 0) return;

      if (e.key === "ArrowRight") {
        e.preventDefault();
        setSelectedPanel((prev) => {
          if (prev == null) return 0;
          return prev < totalPanels - 1 ? prev + 1 : prev;
        });
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        setSelectedPanel((prev) => {
          if (prev == null) return 0;
          return prev > 0 ? prev - 1 : prev;
        });
      } else if (e.key === "a" && selectedPanel != null) {
        e.preventDefault();
        handleApprove();
      } else if (e.key === "r" && selectedPanel != null) {
        e.preventDefault();
        handleReject();
      }
    };

    container.addEventListener("keydown", handleKeyDown);
    return () => container.removeEventListener("keydown", handleKeyDown);
  }, [selectedPanel, totalPanels]);

  const selectedAsset = selectedPanel != null ? getAssetForPanel(selectedPanel) : undefined;
  const selectedGridInfo = selectedPanel != null ? panelToGrid(selectedPanel) : null;

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      className="rounded-xl outline-none"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
      }}
    >
      {/* Scene header */}
      <div className="flex items-center gap-3 px-4 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
        <span
          className="text-xs font-medium px-2 py-0.5 rounded"
          style={{ background: "rgba(212, 168, 68, 0.15)", color: "var(--amber)" }}
        >
          Scene {sceneNum}
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          Act {actNum}
        </span>
        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
          {assets.length} images &middot; {gridUrls.length} grids
        </span>
        {storyboardStatus && (
          <span className="text-[10px] px-1.5 py-0.5 rounded" style={{
            background: storyboardStatus === "prompts_ready" || storyboardStatus === "grids_generated"
              ? "rgba(26, 138, 122, 0.15)"
              : "rgba(212, 168, 68, 0.15)",
            color: storyboardStatus === "prompts_ready" || storyboardStatus === "grids_generated"
              ? "#1A8A7A"
              : "var(--amber)",
          }}>
            {storyboardStatus.replace(/_/g, " ")}
          </span>
        )}
        {approvedCount > 0 && (
          <span className="text-xs ml-auto" style={{ color: "#1A8A7A" }}>
            {approvedCount} approved
          </span>
        )}

        {/* Per-scene action buttons */}
        <div className="flex items-center gap-1.5 ml-auto">
          {hasGrids && (
            <button
              onClick={handleClearScene}
              disabled={sceneTaskRunning}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded transition-opacity disabled:opacity-40"
              style={{ background: "rgba(196, 69, 69, 0.15)", color: "#C44545" }}
              title="Clear grids for this scene"
            >
              <Trash2 size={10} /> Clear
            </button>
          )}
          {!hasPrompts && !sceneTaskRunning && (
            <button
              onClick={handleGeneratePrompts}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded font-medium"
              style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
            >
              <Sparkles size={10} /> Generate Prompts
            </button>
          )}
          {hasPrompts && !hasGrids && !sceneTaskRunning && (
            <button
              onClick={handleGenerateImages}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded font-medium"
              style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
            >
              <Sparkles size={10} /> Generate Grids
            </button>
          )}
          {hasGrids && !sceneTaskRunning && (
            <button
              onClick={async () => {
                await handleClearScene();
                handleGeneratePrompts();
              }}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded font-medium"
              style={{ background: "rgba(212, 168, 68, 0.15)", color: "var(--amber)" }}
              title="Clear and regenerate from scratch"
            >
              <RefreshCw size={10} /> Regenerate
            </button>
          )}
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* Per-scene task progress */}
        {sceneTaskRunning && (
          <div className="flex items-center gap-2 py-2 px-3 rounded-lg" style={{
            background: "rgba(212, 168, 68, 0.08)",
            border: "1px solid rgba(212, 168, 68, 0.2)",
          }}>
            <Loader2 size={14} className="animate-spin" style={{ color: "var(--amber)" }} />
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              {taskMessage || (sceneTaskType === "prompts" ? "Generating prompts..." : "Generating grid images...")}
            </span>
          </div>
        )}

        {sceneResult === "success" && (
          <div className="flex items-center gap-2 py-2 px-3 rounded-lg" style={{
            background: "rgba(26, 138, 122, 0.08)",
            border: "1px solid rgba(26, 138, 122, 0.2)",
          }}>
            <Check size={14} style={{ color: "#1A8A7A" }} />
            <span className="text-xs" style={{ color: "#1A8A7A" }}>Done</span>
          </div>
        )}

        {sceneResult === "error" && (
          <div className="flex items-center gap-2 py-2 px-3 rounded-lg" style={{
            background: "rgba(196, 69, 69, 0.08)",
            border: "1px solid rgba(196, 69, 69, 0.2)",
          }}>
            <X size={14} style={{ color: "#C44545" }} />
            <span className="text-xs" style={{ color: "#C44545" }}>
              {sceneError || "Failed"}
            </span>
          </div>
        )}

        {/* VO player */}
        {scene.voice_over_url && <VoicePlayer audioUrl={scene.voice_over_url} />}

        {/* Empty state — no grids yet */}
        {!hasGrids && !sceneTaskRunning && (
          <div
            className="flex flex-col items-center justify-center py-8 rounded-lg"
            style={{ border: "1px dashed var(--border)", color: "var(--text-muted)" }}
          >
            <span className="text-sm mb-2">No grids generated yet</span>
            <span className="text-xs">
              {hasPrompts
                ? "Prompts ready — click \"Generate Grids\" above"
                : "Click \"Generate Prompts\" above to start"}
            </span>
          </div>
        )}

        {/* Grids side by side */}
        {gridUrls.length > 0 && (
          <div className="flex gap-4 overflow-x-auto pb-2">
            {gridUrls.map((gridUrl, gridIdx) => {
              const panelOffset = gridIdx * 9;
              return (
                <div key={gridIdx} className="flex-shrink-0">
                  <div className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
                    Grid {gridIdx + 1} &middot; panels {panelOffset + 1}-{panelOffset + 9}
                  </div>
                  <div
                    className="relative rounded-lg overflow-hidden cursor-pointer"
                    style={{ width: 280, height: 280 }}
                  >
                    {/* Full grid image */}
                    <img
                      src={gridUrl}
                      alt={`Grid ${gridIdx + 1}`}
                      className="w-full h-full object-cover"
                      draggable={false}
                    />
                    {/* Clickable 3x3 overlay with panel numbers and status */}
                    <div
                      className="absolute inset-0 grid"
                      style={{ gridTemplateColumns: "1fr 1fr 1fr", gridTemplateRows: "1fr 1fr 1fr" }}
                    >
                      {Array.from({ length: 9 }, (_, i) => {
                        const panelNum = panelOffset + i;
                        const status = getStatusForPanel(panelNum);
                        const isSelected = selectedPanel === panelNum;
                        return (
                          <div
                            key={i}
                            onClick={() => setSelectedPanel(panelNum)}
                            className="relative flex items-end justify-between p-1 transition-all"
                            style={{
                              border: isSelected
                                ? "2px solid var(--amber)"
                                : "1px solid rgba(42, 42, 46, 0.4)",
                              background: isSelected ? "rgba(212, 168, 68, 0.1)" : "transparent",
                              cursor: "pointer",
                            }}
                          >
                            <span
                              className="text-[9px] font-medium leading-none px-0.5 rounded"
                              style={{
                                background: "rgba(0,0,0,0.6)",
                                color: "var(--text-secondary)",
                              }}
                            >
                              {panelNum + 1}
                            </span>
                            {status === "approved" && (
                              <Check size={10} style={{ color: "#1A8A7A" }} />
                            )}
                            {status === "rejected" && (
                              <X size={10} style={{ color: "#C44545" }} />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Storyboard prompt */}
        {scene.storyboard_prompts && (
          <PromptExpander prompt={scene.storyboard_prompts} label="Storyboard Prompt" />
        )}

        {/* Panel detail */}
        {selectedPanel != null && selectedGridInfo && gridUrls[selectedGridInfo.gridIndex] && (
          <div
            className="rounded-lg p-4 space-y-3"
            style={{
              background: "var(--bg-card-hover)",
              border: "2px solid var(--amber)",
            }}
          >
            <div className="flex gap-4">
              <PanelMagnifier
                gridUrl={gridUrls[selectedGridInfo.gridIndex]}
                panelIndex={selectedGridInfo.panelInGrid}
                size={200}
              />
              <div className="flex-1 space-y-2">
                <div className="flex items-center gap-2">
                  <span
                    className="text-sm font-medium"
                    style={{ color: "var(--text-primary)" }}
                  >
                    Panel {selectedPanel + 1}
                  </span>
                  {selectedAsset?.shot_type && (
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded"
                      style={{
                        background: "rgba(26, 138, 122, 0.15)",
                        color: "#1A8A7A",
                      }}
                    >
                      {selectedAsset.shot_type}
                    </span>
                  )}
                </div>
                {selectedAsset?.sentence_text && (
                  <p
                    className="text-xs leading-relaxed"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {selectedAsset.sentence_text}
                  </p>
                )}
                {!selectedAsset && (
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                    No asset data for this panel
                  </p>
                )}

                {/* Action buttons */}
                <div className="flex gap-2 pt-2">
                  <button
                    onClick={handleApprove}
                    disabled={actionLoading || !selectedAsset}
                    className="flex items-center gap-1 text-xs px-3 py-1.5 rounded font-medium transition-opacity"
                    style={{
                      background: "#1A8A7A",
                      color: "#fff",
                      opacity: actionLoading || !selectedAsset ? 0.5 : 1,
                    }}
                  >
                    <Check size={12} /> Approve
                  </button>
                  <button
                    onClick={handleReject}
                    disabled={actionLoading || !selectedAsset}
                    className="flex items-center gap-1 text-xs px-3 py-1.5 rounded font-medium transition-opacity"
                    style={{
                      background: "transparent",
                      border: "1px solid #C44545",
                      color: "#C44545",
                      opacity: actionLoading || !selectedAsset ? 0.5 : 1,
                    }}
                  >
                    <X size={12} /> Reject
                  </button>
                  <span className="text-[10px] self-center ml-2" style={{ color: "var(--text-muted)" }}>
                    Keys: A approve &middot; R reject &middot; &larr;&rarr; navigate
                  </span>
                </div>
              </div>
            </div>

            {/* Image prompt expander */}
            {selectedAsset?.image_prompt && (
              <PromptExpander prompt={selectedAsset.image_prompt} label="Image Prompt" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
