"use client";

import { useState, useCallback } from "react";
import { Check, Loader2, Play, AlertTriangle, Sparkles, Film, ChevronRight } from "lucide-react";
import { motion } from "framer-motion";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { SystemPromptEditor } from "@/components/ui/SystemPromptEditor";
import { ActionButton } from "@/components/ui/ActionButton";
import { getVideoAssets, runPipelineStage, clearStaleTask, updateVideoStyles, advanceVideo, getDefaultVideoMotionPrompt, updateVideo } from "@/lib/api";
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
  onAdvanced?: () => void;
}

export function VideoClipsTab({ video, onAdvanced }: VideoClipsTabProps) {
  const queryClient = useQueryClient();
  const [model, setModel] = useState(video.video_model || "grok-imagine");
  const [savingModel, setSavingModel] = useState(false);
  const [confirmGenerate, setConfirmGenerate] = useState(false);
  const [isGeneratingPrompts, setIsGeneratingPrompts] = useState(false);
  const [isGeneratingClips, setIsGeneratingClips] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);
  const [taskStage, setTaskStage] = useState<"prompts" | "clips">("prompts");
  const [advancing, setAdvancing] = useState(false);

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

  // Hero shots first; fallback to all assets with video content, prompts, or images
  const heroShots = assets.filter((a) => a.hero_shot);
  const clips = heroShots.length > 0
    ? heroShots
    : assets.filter((a) => a.video_clip_url || a.image_prompt || a.image_url);

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

  const handleAdvanceStage = useCallback(async () => {
    setAdvancing(true);
    try {
      await advanceVideo(video.id);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
      onAdvanced?.();
    } catch (err) {
      alert(`Advance failed: ${(err as Error).message}`);
    } finally {
      setAdvancing(false);
    }
  }, [video.id, queryClient, onAdvanced]);

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
    <div className="space-y-4">
      {/* Top action bar */}
      <div className="rounded-xl px-4 py-3" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
        {/* Status row */}
        <div className="flex items-center gap-4 text-[10px] font-mono mb-3" style={{ color: "var(--text-tertiary)" }}>
          <span>Clips <strong style={{ color: doneCount === totalCount && totalCount > 0 ? "var(--green)" : "var(--text-secondary)" }}>{doneCount}/{totalCount}</strong></span>
          <span>Prompts <strong style={{ color: "var(--text-secondary)" }}>{clips.filter(a => a.image_prompt).length}/{totalCount}</strong></span>
          <span>Pending <strong style={{ color: pendingCount > 0 ? "var(--orange)" : "var(--green)" }}>{pendingCount}</strong></span>
          <span>Cost <strong style={{ color: "var(--gold)" }}>${estimatedCost.toFixed(2)}</strong></span>
          <span>
            <select
              value={model}
              onChange={(e) => handleModelChange(e.target.value)}
              disabled={savingModel}
              className="bg-transparent text-[10px] font-mono border rounded px-1 py-0.5 cursor-pointer"
              style={{ color: "var(--text-secondary)", borderColor: "rgba(255,255,255,0.1)" }}
            >
              <option value="grok-imagine">Grok Imagine</option>
              <option value="veo-3.1-fast">Veo 3.1 Fast</option>
              <option value="veo-3.1-quality">Veo 3.1 Quality</option>
              <option value="kling-3.0-pro">Kling 3.0 Pro</option>
              <option value="runway-gen4-turbo">Runway Gen-4 Turbo</option>
              <option value="hailuo-2.3-standard">Hailuo 2.3 Standard</option>
            </select>
          </span>
        </div>
        {/* Action buttons row */}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={handleGeneratePrompts}
            disabled={isGeneratingPrompts || taskRunning}
            className="px-3 py-1.5 rounded-lg text-[10px] font-semibold disabled:opacity-40 transition-all hover:brightness-110"
            style={{ background: "var(--purple)", color: "var(--bg-void)" }}
          >
            {(isGeneratingPrompts || (taskRunning && taskStage === "prompts")) ? <Loader2 size={12} className="animate-spin inline mr-1" /> : <Sparkles size={12} className="inline mr-1" />}
            Generate Prompts
          </button>
          <button
            onClick={confirmGenerate ? handleGenerateClips : () => setConfirmGenerate(true)}
            disabled={isGeneratingClips || taskRunning}
            className="px-3 py-1.5 rounded-lg text-[10px] font-semibold disabled:opacity-40 transition-all hover:brightness-110"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            {(isGeneratingClips || (taskRunning && taskStage === "clips")) ? <Loader2 size={12} className="animate-spin inline mr-1" /> : <Film size={12} className="inline mr-1" />}
            {confirmGenerate ? `Confirm — $${estimatedCost.toFixed(2)}` : "Generate All Clips"}
          </button>
          {confirmGenerate && (
            <button
              onClick={() => setConfirmGenerate(false)}
              className="px-3 py-1.5 rounded-lg text-[10px] font-semibold transition-all hover:brightness-110"
              style={{ color: "var(--text-tertiary)" }}
            >
              Cancel
            </button>
          )}
          <div className="flex-1" />
          <button onClick={handleAdvanceStage} disabled={advancing}
            className="px-3 py-1.5 rounded-lg text-[10px] font-semibold inline-flex items-center gap-1 disabled:opacity-50 transition-all hover:brightness-110"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
            {advancing ? <Loader2 size={12} className="animate-spin" /> : null}
            Advance Stage <ChevronRight size={12} />
          </button>
        </div>
      </div>

      {/* Video Motion System Prompt */}
      <SystemPromptEditor
        label="Video Motion System Prompt"
        currentValue={video.video_motion_system_prompt}
        onSave={async (text) => {
          await updateVideo(video.id, { video_motion_system_prompt: text || null });
          queryClient.invalidateQueries({ queryKey: ["video", video.id] });
        }}
        onReset={async () => {
          const res = await getDefaultVideoMotionPrompt();
          await updateVideo(video.id, { video_motion_system_prompt: null });
          queryClient.invalidateQueries({ queryKey: ["video", video.id] });
          return res.prompt;
        }}
      />

    <div className="grid grid-cols-1 gap-6">
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

      {/* Sidebar removed — all controls in top bar */}
    </div>
    </div>
  );
}
