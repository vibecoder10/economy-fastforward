"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  Play, Pause, Check, Loader2, Pencil, Image as ImageIcon, RefreshCw,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { StatusPill } from "@/components/ui/StatusPill";
import { MiniWaveform } from "@/components/ui/MiniWaveform";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { ActionButton } from "@/components/ui/ActionButton";
import {
  getVideoScript, getVideoAssets, updateStoryboardMode,
  runPipelineStage, updateSceneSegments, runImageForSegment, clearStaleTask, updateVideoStyles,
} from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import type { VideoDetail, ScriptScene as ApiScriptScene, Asset } from "@/lib/api";
import { StopGenerationButton } from "@/components/production/StopGenerationButton";
import { toDisplayImageUrl } from "@/lib/utils";

interface VisualsTabProps {
  video: VideoDetail & { id: string };
}

const STATUS_ICON: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  done: { icon: <Check size={10} />, color: "var(--green)", label: "Generated" },
  generating: { icon: <Loader2 size={10} className="animate-spin" />, color: "var(--purple)", label: "Generating" },
  pending: { icon: <ImageIcon size={10} />, color: "var(--text-tertiary)", label: "Pending" },
};

interface VisualSegment {
  id: string;
  segmentId: string;
  sentenceText: string;
  imagePrompt: string;
  imageUrl: string | undefined;
  status: "pending" | "generating" | "done";
  sceneNumber: number;
  imageIndex: number;
}

interface SceneGroup {
  sceneNumber: number;
  actNumber: number;
  narrationText: string;
  duration: string;
  segments: VisualSegment[];
}

export function VisualsTab({ video }: VisualsTabProps) {
  const queryClient = useQueryClient();

  const { data: scriptScenes, isLoading: loadingScripts } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });

  const { data: assets, isLoading: loadingAssets } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });

  const computedScenes = useMemo<SceneGroup[]>(() => {
    if (!scriptScenes || !assets) return [];
    const totalScenes = scriptScenes.length;
    return scriptScenes.map((scene) => ({
      sceneNumber: scene.scene || 0,
      actNumber: Math.ceil((scene.scene || 1) / Math.ceil(totalScenes / 6)),
      narrationText: scene.scene_text || "",
      duration: `${Math.round((scene.scene_text || "").split(/\s+/).length / 2.5)}s`,
      segments: assets
        .filter((a) => a.scene === scene.scene)
        .sort((a, b) => (a.image_index || 0) - (b.image_index || 0))
        .map((asset) => ({
          id: asset.id,
          segmentId: `S-${String(asset.scene || 0).padStart(2, "0")}.${asset.image_index || 0}`,
          sentenceText: asset.sentence_text || "",
          imagePrompt: asset.image_prompt || "",
          imageUrl: asset.image_url || undefined,
          status: (asset.status === "approved" || asset.status === "Done" || asset.image_url)
            ? ("done" as const)
            : ("pending" as const),
          sceneNumber: asset.scene || 0,
          imageIndex: asset.image_index || 0,
        })),
    }));
  }, [scriptScenes, assets]);

  const [scenes, setScenes] = useState<SceneGroup[]>([]);
  const [editingPrompt, setEditingPrompt] = useState<string | null>(null);
  const [regeneratingSegment, setRegeneratingSegment] = useState<string | null>(null);
  const [generatingAll, setGeneratingAll] = useState(false);
  const [model, setModel] = useState(video.image_model_override || "nano-banana-2");
  const [savingModel, setSavingModel] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: taskRunning,
    interval: 3000,
    onComplete: () => {
      setTaskRunning(false);
      setGeneratingAll(false);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setGeneratingAll(false);
      alert(`Image generation failed: ${error}`);
    },
  });

  useEffect(() => {
    if (computedScenes.length > 0 && scenes.length === 0) {
      setScenes(computedScenes);
    }
  }, [computedScenes, scenes.length]);

  useEffect(() => {
    setModel(video.image_model_override || "nano-banana-2");
  }, [video.image_model_override]);

  const totalSegments = scenes.reduce((sum, s) => sum + s.segments.length, 0);
  const doneSegments = scenes.reduce(
    (sum, s) => sum + s.segments.filter((seg) => seg.status === "done").length,
    0,
  );
  const pendingSegments = totalSegments - doneSegments;
  const estimatedCostDone = doneSegments * 0.025;
  const estimatedCostTotal = totalSegments * 0.025;

  const updatePrompt = (segId: string, newPrompt: string) => {
    setScenes((prev) =>
      prev.map((scene) => ({
        ...scene,
        segments: scene.segments.map((seg) =>
          seg.id === segId ? { ...seg, imagePrompt: newPrompt } : seg,
        ),
      })),
    );
  };

  const persistSegment = useCallback(async (segId: string) => {
    const scene = scenes.find((s) => s.segments.some((seg) => seg.id === segId));
    if (!scene) return;
    const updatedSegments = scene.segments.map((seg) => ({
      image_index: seg.imageIndex,
      sentence_text: seg.sentenceText,
    }));
    try {
      await updateSceneSegments(video.id, scene.sceneNumber, updatedSegments);
    } catch {
      // silent
    }
  }, [scenes, video.id]);

  const handleRegenerate = useCallback(async (seg: VisualSegment) => {
    setRegeneratingSegment(seg.id);
    try {
      await runImageForSegment(video.id, seg.sceneNumber, seg.imageIndex);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } finally {
      setRegeneratingSegment(null);
    }
  }, [video.id, queryClient]);

  const handleGenerateAll = useCallback(async () => {
    setGeneratingAll(true);
    try {
      await runPipelineStage(video.id, "images");
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "images");
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          alert(`Image generation failed: ${(retryErr as Error).message}`);
        }
      } else {
        alert(`Image generation failed: ${message}`);
      }
      setGeneratingAll(false);
    }
  }, [video.id]);

  const handleModelChange = useCallback(async (nextModel: string) => {
    setModel(nextModel);
    setSavingModel(true);
    try {
      await updateVideoStyles(video.id, { image_model_override: nextModel });
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      alert(`Failed to update image model: ${(err as Error).message}`);
      setModel(video.image_model_override || "nano-banana-2");
    } finally {
      setSavingModel(false);
    }
  }, [queryClient, video.id, video.image_model_override]);

  // Group by act
  const actGroups = scenes.reduce<Record<number, SceneGroup[]>>((acc, scene) => {
    if (!acc[scene.actNumber]) acc[scene.actNumber] = [];
    acc[scene.actNumber].push(scene);
    return acc;
  }, {});

  if (loadingScripts || loadingAssets) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--purple)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>Loading visuals...</span>
      </div>
    );
  }

  if (scenes.length === 0) {
    return (
      <GlassCard className="p-12 text-center">
        <ImageIcon size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>No Visual Segments Yet</p>
        <p className="text-sm mb-6" style={{ color: "var(--text-tertiary)" }}>
          Generate scripts and image prompts first. Current stage: <span style={{ color: "var(--purple)" }}>{(video.status || "").replace(/_/g, " ")}</span>
        </p>
        <button
          onClick={handleGenerateAll}
          disabled={generatingAll || taskRunning}
          className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-base font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
          style={{ background: "var(--purple)", color: "var(--bg-void)" }}
        >
          {(generatingAll || taskRunning) ? <Loader2 size={18} className="animate-spin" /> : <ImageIcon size={18} />}
          {taskRunning ? (taskMessage || "Generating Visuals...") : generatingAll ? "Starting..." : "Generate Visuals"}
        </button>
      </GlassCard>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_260px] gap-6">
      {/* Main content */}
      <div className="space-y-6">
        {Object.entries(actGroups).map(([actNum, actScenes]) => (
          <div key={actNum}>
            <div className="flex items-center gap-4 mb-4">
              <div className="flex-1 h-px" style={{ background: "var(--purple)", opacity: 0.3 }} />
              <span
                className="text-xs font-semibold uppercase tracking-wider"
                style={{ color: "var(--purple)" }}
              >
                Act {actNum}
              </span>
              <div className="flex-1 h-px" style={{ background: "var(--purple)", opacity: 0.3 }} />
            </div>

            <div className="space-y-4">
              {actScenes.map((scene) => (
                <GlassCard key={scene.sceneNumber} className="p-5">
                  {/* Scene header */}
                  <div className="flex items-start gap-3 mb-4">
                    <SegmentBadge label={`Scene ${scene.sceneNumber}`} color="var(--purple)" />
                    <div className="flex-1">
                      <p
                        className="text-sm leading-relaxed"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {scene.narrationText}
                      </p>
                      <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                        {scene.duration}
                      </span>
                    </div>
                  </div>

                  {/* Segment cards */}
                  <div className="space-y-3">
                    {scene.segments.map((seg) => {
                      const statusInfo = STATUS_ICON[seg.status];
                      const isEditing = editingPrompt === seg.id;
                      const isRegenerating = regeneratingSegment === seg.id;

                      return (
                        <div
                          key={seg.id}
                          className="rounded-xl p-3 transition-all"
                          style={{
                            background: "rgba(255,255,255,0.02)",
                            border: `1px solid ${
                              seg.status === "done"
                                ? "rgba(0, 230, 138, 0.15)"
                                : "rgba(255,255,255,0.05)"
                            }`,
                          }}
                        >
                          <div className="flex items-start gap-3">
                            <SegmentBadge
                              label={seg.segmentId}
                              color={seg.status === "done" ? "var(--green)" : undefined}
                            />
                            <div className="flex-1 min-w-0 space-y-2">
                              {/* Sentence text */}
                              <div>
                                <label
                                  className="text-[9px] uppercase tracking-wider font-medium"
                                  style={{ color: "var(--text-tertiary)" }}
                                >
                                  Sentence
                                </label>
                                <p
                                  className="text-sm mt-0.5"
                                  style={{ color: "var(--text-primary)" }}
                                >
                                  {seg.sentenceText || "—"}
                                </p>
                              </div>

                              {/* Image prompt (editable) */}
                              <div>
                                <div className="flex items-center gap-1.5">
                                  <label
                                    className="text-[9px] uppercase tracking-wider font-medium"
                                    style={{ color: "var(--purple)" }}
                                  >
                                    Image Prompt
                                  </label>
                                  <Pencil size={8} style={{ color: "var(--purple)", opacity: 0.5 }} />
                                </div>
                                <textarea
                                  value={seg.imagePrompt}
                                  onChange={(e) => updatePrompt(seg.id, e.target.value)}
                                  rows={isEditing ? 4 : 2}
                                  className="w-full text-[12px] font-mono outline-none rounded-lg px-2 py-1 mt-0.5 resize-none transition-all"
                                  style={{
                                    color: "var(--text-secondary)",
                                    background: "transparent",
                                    border: "1px solid transparent",
                                  }}
                                  onFocus={(e) => {
                                    setEditingPrompt(seg.id);
                                    e.target.style.background = "var(--bg-elevated)";
                                    e.target.style.borderColor = "var(--purple)";
                                  }}
                                  onBlur={(e) => {
                                    setEditingPrompt(null);
                                    e.target.style.background = "transparent";
                                    e.target.style.borderColor = "transparent";
                                    persistSegment(seg.id);
                                  }}
                                />
                              </div>
                            </div>

                            {/* Thumbnail + status + regenerate */}
                            <div className="shrink-0 flex flex-col items-center gap-1.5">
                              <div
                                className="w-20 h-14 rounded-lg relative flex items-center justify-center overflow-hidden"
                                style={{
                                  background: "var(--bg-elevated)",
                                  border: "1px solid var(--border-subtle)",
                                }}
                              >
                                {seg.imageUrl ? (
                                  <img
                                    src={toDisplayImageUrl(seg.imageUrl)}
                                    alt={seg.segmentId}
                                    className="absolute inset-0 w-full h-full object-cover"
                                  />
                                ) : (
                                  <svg className="absolute inset-0 w-full h-full opacity-15">
                                    <defs>
                                      <pattern
                                        id={`vg-${seg.id}`}
                                        width="12"
                                        height="12"
                                        patternUnits="userSpaceOnUse"
                                      >
                                        <path
                                          d="M 12 0 L 0 0 0 12"
                                          fill="none"
                                          stroke="var(--purple)"
                                          strokeWidth="0.3"
                                        />
                                      </pattern>
                                    </defs>
                                    <rect
                                      width="100%"
                                      height="100%"
                                      fill={`url(#vg-${seg.id})`}
                                    />
                                  </svg>
                                )}
                                {seg.status === "done" && (
                                  <div
                                    className="absolute top-1 right-1 w-4 h-4 rounded-full flex items-center justify-center"
                                    style={{ background: "var(--green)" }}
                                  >
                                    <Check size={8} style={{ color: "var(--bg-void)" }} />
                                  </div>
                                )}
                              </div>
                              <span
                                className="text-[9px] font-mono flex items-center gap-1"
                                style={{ color: statusInfo.color }}
                              >
                                {statusInfo.icon}
                                {statusInfo.label}
                              </span>
                              <button
                                onClick={() => handleRegenerate(seg)}
                                disabled={isRegenerating}
                                className="text-[9px] px-2 py-0.5 rounded transition-all disabled:opacity-50"
                                style={{
                                  color: "var(--orange)",
                                  border: "1px solid var(--orange)",
                                }}
                              >
                                {isRegenerating ? (
                                  <Loader2 size={8} className="animate-spin inline" />
                                ) : (
                                  <RefreshCw size={8} className="inline" />
                                )}{" "}
                                {seg.status === "done" ? "Regen" : "Gen"}
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </GlassCard>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Right sidebar */}
      <div className="space-y-4">
        <GlassCard className="p-5">
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-4"
            style={{ color: "var(--text-secondary)" }}
          >
            Generation Stats
          </h3>
          <div className="flex justify-center mb-4">
            <ProgressRing
              value={totalSegments > 0 ? (doneSegments / totalSegments) * 100 : 0}
              size={90}
              color="var(--purple)"
              strokeWidth={7}
            >
              <span className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
                {doneSegments}
              </span>
              <span className="text-[8px] uppercase" style={{ color: "var(--text-secondary)" }}>
                / {totalSegments}
              </span>
            </ProgressRing>
          </div>

          <FilterSelect
            label="Model"
            options={[
              { value: "nano-banana-2", label: "Nano Banana 2" },
              { value: "z-image", label: "Z Image" },
            ]}
            value={model}
            onChange={handleModelChange}
            className="mb-3"
            disabled={savingModel}
            title={savingModel ? "Saving image model override..." : "Choose the image generation model for this video."}
          />
          <p className="text-[10px] mb-3" style={{ color: "var(--text-tertiary)" }}>
            {savingModel ? "Saving model override..." : "This override is saved on the video and used by image generation."}
          </p>

          <div className="pt-3" style={{ borderTop: "1px solid var(--border-subtle)" }}>
            <p className="text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>
              Cost Tracker
            </p>
            <p className="text-lg font-mono" style={{ color: "var(--gold)" }}>
              ${estimatedCostDone.toFixed(3)}{" "}
              <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                / ${estimatedCostTotal.toFixed(2)}
              </span>
            </p>
          </div>
        </GlassCard>

        <div className="flex items-stretch gap-2">
          <ActionButton
            variant="filled"
            icon={(generatingAll || taskRunning) ? Loader2 : ImageIcon}
            className="w-full"
            onClick={handleGenerateAll}
            disabled={generatingAll || taskRunning || pendingSegments === 0}
          >
            {taskRunning
              ? (taskMessage || "Generating...")
              : generatingAll
                ? "Starting..."
                : `Generate All Remaining (${pendingSegments})`}
          </ActionButton>
          <StopGenerationButton videoId={video.id} running={taskRunning} />
        </div>
      </div>
    </div>
  );
}
