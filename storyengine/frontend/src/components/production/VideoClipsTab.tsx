"use client";

import { useState, useCallback } from "react";
import { Check, Loader2, Play, AlertTriangle, Sparkles, Film } from "lucide-react";
import { motion } from "framer-motion";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { ActionButton } from "@/components/ui/ActionButton";
import { getVideoAssets, runPipelineStage, clearStaleTask, updateVideoStyles } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import type { VideoDetail, Asset } from "@/lib/api";

function getClipStatus(asset: Asset): "pending" | "generating" | "done" {
  if (asset.video_clip_url) return "done";
  if (asset.status === "generating" || asset.status === "processing") return "generating";
  return "pending";
}

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  done: { label: "Generated", color: "green" },
  generating: { label: "Generating", color: "purple" },
  pending: { label: "Pending", color: "orange" },
};

interface VideoClipsTabProps {
  video: VideoDetail & { id: string };
}

export function VideoClipsTab({ video }: VideoClipsTabProps) {
  const queryClient = useQueryClient();
  const [model, setModel] = useState(video.video_model || "grok-imagine");
  const [savingModel, setSavingModel] = useState(false);
  const [confirmGenerate, setConfirmGenerate] = useState(false);
  const [isGeneratingPrompts, setIsGeneratingPrompts] = useState(false);
  const [isGeneratingClips, setIsGeneratingClips] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);
  const [taskStage, setTaskStage] = useState<"prompts" | "clips">("prompts");

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: taskRunning,
    interval: 3000,
    onComplete: () => {
      setTaskRunning(false);
      if (taskStage === "prompts") setIsGeneratingPrompts(false);
      else { setIsGeneratingClips(false); setConfirmGenerate(false); }
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      if (taskStage === "prompts") setIsGeneratingPrompts(false);
      else { setIsGeneratingClips(false); setConfirmGenerate(false); }
      alert(`${taskStage === "prompts" ? "Prompt generation" : "Clip generation"} failed: ${error}`);
    },
  });

  const { data: assets = [] } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });

  const modelLabels: Record<string, string> = {
    "grok-imagine": "Grok Imagine",
    "veo-3.1-fast": "Veo 3.1 Fast",
    "veo-3.1-quality": "Veo 3.1 Quality",
    "kling-3.0-pro": "Kling 3.0 Pro",
    "runway-gen4-turbo": "Runway Gen-4 Turbo",
    "hailuo-2.3-standard": "Hailuo 2.3 Standard",
  };

  const selectedModelLabel = modelLabels[model] || model;

  // Hero shots first; fallback to all assets with video content or prompts
  const heroShots = assets.filter((a) => a.hero_shot);
  const clips = heroShots.length > 0
    ? heroShots
    : assets.filter((a) => a.video_clip_url || a.image_prompt);

  const doneCount = clips.filter((a) => getClipStatus(a) === "done").length;
  const generatingCount = clips.filter((a) => getClipStatus(a) === "generating").length;
  const pendingCount = clips.filter((a) => getClipStatus(a) === "pending").length;
  const totalCount = clips.length;
  const progressPct = totalCount > 0 ? (doneCount / totalCount) * 100 : 0;
  const estimatedCost = totalCount * 0.3;

  const handleModelChange = useCallback(async (nextModel: string) => {
    setModel(nextModel);
    setSavingModel(true);
    try {
      await updateVideoStyles(video.id, { video_model: nextModel });
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      alert(`Failed to update video model: ${(err as Error).message}`);
      setModel(video.video_model || "grok-imagine");
    } finally {
      setSavingModel(false);
    }
  }, [queryClient, video.id, video.video_model]);

  const handleGeneratePrompts = useCallback(async () => {
    setIsGeneratingPrompts(true);
    try {
      await runPipelineStage(video.id, "video-scripts");
      setTaskStage("prompts");
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "video-scripts");
          setTaskStage("prompts");
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          alert(`Prompt generation failed: ${(retryErr as Error).message}`);
        }
      } else {
        alert(`Prompt generation failed: ${message}`);
      }
      setIsGeneratingPrompts(false);
    }
  }, [video.id]);

  const handleGenerateClips = useCallback(async () => {
    setIsGeneratingClips(true);
    try {
      await runPipelineStage(video.id, "video-generation");
      setTaskStage("clips");
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "video-generation");
          setTaskStage("clips");
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          alert(`Clip generation failed: ${(retryErr as Error).message}`);
        }
      } else {
        alert(`Clip generation failed: ${message}`);
      }
      setIsGeneratingClips(false);
      setConfirmGenerate(false);
    }
  }, [video.id]);

  if (totalCount === 0) {
    return (
      <GlassCard className="p-12 text-center">
        <Film size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          No Video Clips Yet
        </p>
        <p className="text-sm mb-4" style={{ color: "var(--text-tertiary)" }}>
          Generate video prompts first, then generate clips from hero shots.
        </p>
        <ActionButton
          variant="outline"
          icon={(isGeneratingPrompts || (taskRunning && taskStage === "prompts")) ? Loader2 : Sparkles}
          onClick={handleGeneratePrompts}
          disabled={isGeneratingPrompts || taskRunning}
        >
          {(taskRunning && taskStage === "prompts") ? (taskMessage || "Generating...") : isGeneratingPrompts ? "Starting..." : "Generate Video Prompts"}
        </ActionButton>
      </GlassCard>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      {/* Clip grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {clips.map((asset, idx) => {
          const status = getClipStatus(asset);
          const cfg = STATUS_CONFIG[status];
          // Use scene + image_index for display label
          const sceneNum = asset.scene ?? 0;
          const imageIdx = asset.image_index ?? (idx + 1);

          return (
            <GlassCard key={asset.id} className="p-0 overflow-hidden">
              {/* Video/image placeholder */}
              <div
                className="aspect-video relative flex items-center justify-center"
                style={{ background: "var(--bg-elevated)" }}
              >
                {asset.image_url && status !== "done" && (
                  <img
                    src={asset.image_url}
                    alt={`Scene ${sceneNum}`}
                    className="absolute inset-0 w-full h-full object-cover opacity-60"
                  />
                )}

                {status === "done" && asset.video_clip_url && (
                  <video
                    src={asset.video_clip_url}
                    className="absolute inset-0 w-full h-full object-cover"
                    muted
                    loop
                    playsInline
                    onMouseEnter={(e) => (e.target as HTMLVideoElement).play()}
                    onMouseLeave={(e) => {
                      const v = e.target as HTMLVideoElement;
                      v.pause();
                      v.currentTime = 0;
                    }}
                  />
                )}

                {!asset.image_url && status !== "done" && (
                  <svg className="absolute inset-0 w-full h-full opacity-10">
                    <defs>
                      <pattern
                        id={`vc-grid-${asset.id}`}
                        width="30"
                        height="30"
                        patternUnits="userSpaceOnUse"
                      >
                        <path d="M 30 0 L 0 0 0 30" fill="none" stroke="var(--purple)" strokeWidth="0.5" />
                      </pattern>
                    </defs>
                    <rect width="100%" height="100%" fill={`url(#vc-grid-${asset.id})`} />
                  </svg>
                )}

                {status === "done" && (
                  <div
                    className="absolute top-2 right-2 w-7 h-7 rounded-full flex items-center justify-center z-10"
                    style={{ background: "rgba(0, 230, 138, 0.2)", color: "var(--green)" }}
                  >
                    <Check size={14} />
                  </div>
                )}

                {status === "generating" && (
                  <motion.div
                    className="absolute inset-0 z-10 flex items-center justify-center"
                    animate={{ opacity: [0.4, 1, 0.4] }}
                    transition={{ duration: 2, repeat: Infinity }}
                  >
                    <div
                      className="w-12 h-12 rounded-full flex items-center justify-center"
                      style={{ background: "rgba(139, 92, 246, 0.25)" }}
                    >
                      <Loader2 size={20} className="animate-spin" style={{ color: "var(--purple)" }} />
                    </div>
                  </motion.div>
                )}

                {status === "pending" && !asset.image_url && (
                  <Film size={28} style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
                )}

                {status === "done" && (
                  <button
                    className="absolute inset-0 flex items-center justify-center z-10 opacity-0 hover:opacity-100 transition-opacity"
                    style={{ background: "rgba(0,0,0,0.5)" }}
                  >
                    <Play size={32} style={{ color: "white" }} />
                  </button>
                )}
              </div>

              {/* Info */}
              <div className="p-3">
                <div className="flex items-center gap-2 mb-2">
                  <SegmentBadge
                    label={`S-${String(sceneNum).padStart(2, "0")}.${imageIdx}`}
                    color={status === "generating" ? "var(--purple)" : undefined}
                  />
                  <StatusPill
                    label={cfg.label}
                    color={cfg.color}
                    pulse={status === "generating"}
                  />
                </div>
                <p
                  className="text-[11px] leading-relaxed line-clamp-2"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {asset.sentence_text || asset.image_prompt || "No prompt"}
                </p>
              </div>
            </GlassCard>
          );
        })}
      </div>

      {/* Sidebar */}
      <div className="space-y-4">
        {/* Stats */}
        <GlassCard className="p-5">
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-4"
            style={{ color: "var(--text-secondary)" }}
          >
            Clip Stats
          </h3>
          <div className="flex justify-center mb-4">
            <ProgressRing value={progressPct} size={90} color="var(--purple)" strokeWidth={7}>
              <span className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
                {doneCount}
              </span>
              <span className="text-[8px] uppercase" style={{ color: "var(--text-secondary)" }}>
                / {totalCount}
              </span>
            </ProgressRing>
          </div>
          <div className="space-y-3">
            {[
              { label: "Total Clips", value: String(totalCount) },
              { label: "Generated", value: String(doneCount), color: "var(--green)" },
              { label: "Generating", value: String(generatingCount), color: "var(--purple)" },
              { label: "Pending", value: String(pendingCount), color: "var(--orange)" },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  {row.label}
                </span>
                <span
                  className="text-sm font-mono font-medium"
                  style={{ color: row.color || "var(--text-primary)" }}
                >
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Model selector */}
        <GlassCard className="p-5">
          <FilterSelect
            label="Video Model"
            options={[
              { value: "grok-imagine", label: "Grok Imagine" },
              { value: "veo-3.1-fast", label: "Veo 3.1 Fast" },
              { value: "veo-3.1-quality", label: "Veo 3.1 Quality" },
              { value: "kling-3.0-pro", label: "Kling 3.0 Pro" },
              { value: "runway-gen4-turbo", label: "Runway Gen-4 Turbo" },
              { value: "hailuo-2.3-standard", label: "Hailuo 2.3 Standard" },
            ]}
            value={model}
            onChange={handleModelChange}
            disabled={savingModel}
            title={savingModel ? "Saving video model override..." : "Choose the clip generation model for this video."}
          />
          <p className="text-[10px] mt-3" style={{ color: "var(--text-tertiary)" }}>
            {savingModel ? "Saving video model override..." : `Saved model: ${selectedModelLabel}`}
          </p>
          <div className="pt-3 mt-3" style={{ borderTop: "1px solid var(--border-subtle)" }}>
            <p className="text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>
              Estimated Cost
            </p>
            <p className="text-lg font-mono" style={{ color: "var(--gold)" }}>
              ${estimatedCost.toFixed(2)}
            </p>
          </div>
        </GlassCard>

        {/* Cost warning */}
        <GlassCard className="p-4" style={{ borderColor: "var(--orange)", borderWidth: 1 }}>
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" style={{ color: "var(--orange)" }} />
            <p className="text-[11px] leading-relaxed" style={{ color: "var(--orange)" }}>
              Video generation costs ~$0.30 per clip. Review prompts carefully before generating.
            </p>
          </div>
        </GlassCard>

        {/* Actions */}
        <div className="space-y-2">
          <ActionButton
            variant="outline"
            icon={(isGeneratingPrompts || (taskRunning && taskStage === "prompts")) ? Loader2 : Sparkles}
            className="w-full"
            onClick={handleGeneratePrompts}
            disabled={isGeneratingPrompts || taskRunning}
          >
            {(taskRunning && taskStage === "prompts") ? (taskMessage || "Generating...") : isGeneratingPrompts ? "Starting..." : "Generate Prompts"}
          </ActionButton>
          {confirmGenerate ? (
            <ActionButton
              variant="filled"
              icon={(isGeneratingClips || (taskRunning && taskStage === "clips")) ? Loader2 : Film}
              className="w-full"
              onClick={handleGenerateClips}
              disabled={isGeneratingClips || taskRunning}
            >
              {(taskRunning && taskStage === "clips") ? (taskMessage || "Generating...") : isGeneratingClips ? "Starting..." : `Confirm — $${estimatedCost.toFixed(2)}`}
            </ActionButton>
          ) : (
            <ActionButton
              variant="filled"
              icon={Film}
              className="w-full"
              onClick={() => setConfirmGenerate(true)}
            >
              Generate All Clips
            </ActionButton>
          )}
        </div>
      </div>
    </div>
  );
}
