"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { Check, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { ScriptScene, Asset, approveAsset, rejectAsset } from "@/lib/api";
import { VoicePlayer } from "./voice-player";
import { PanelMagnifier } from "./panel-magnifier";
import { PromptExpander } from "./prompt-expander";

interface StoryboardViewerProps {
  scene: ScriptScene;
  assets: Asset[];
  videoId: string;
  onRefresh: () => void;
}

function panelToGrid(panelNum: number): { gridIndex: number; panelInGrid: number } {
  return { gridIndex: Math.floor(panelNum / 9), panelInGrid: panelNum % 9 };
}

export function StoryboardViewer({ scene, assets, videoId, onRefresh }: StoryboardViewerProps) {
  const [selectedPanel, setSelectedPanel] = useState<number | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const gridUrls = [
    scene.storyboard_1_url,
    scene.storyboard_2_url,
    scene.storyboard_3_url,
  ].filter((url): url is string => url != null);

  const totalPanels = gridUrls.length * 9;

  const approvedCount = assets.filter((a) => a.status === "approved").length;

  // Build a map from image_index to asset for quick lookup
  const assetByIndex = new Map<number, Asset>();
  for (const asset of assets) {
    if (asset.image_index != null) {
      assetByIndex.set(asset.image_index, asset);
    }
  }

  // Compute the act label from scene number
  const sceneNum = scene.scene ?? 0;
  const actNum = Math.ceil(sceneNum / 4) || 1;

  const getAssetForPanel = useCallback(
    (panelNum: number): Asset | undefined => {
      // Panel numbers are continuous: grid 0 = panels 0-8, grid 1 = 9-17, etc.
      // Image indices in Airtable are typically 1-based per scene
      // Assets are filtered to this scene, so match by image_index
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
        {approvedCount > 0 && (
          <span className="text-xs ml-auto" style={{ color: "#1A8A7A" }}>
            {approvedCount} approved
          </span>
        )}
      </div>

      <div className="p-4 space-y-4">
        {/* VO player */}
        {scene.voice_over_url && <VoicePlayer audioUrl={scene.voice_over_url} />}

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
