"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getVideos,
  getVideo,
  runNextStep,
  runPipelineStage,
  getPipelineTaskStatus,
  type VideoSummary,
  type VideoDetail,
} from "@/lib/api";
import { VideoCard } from "@/components/video-card";
import { DetailPanel } from "@/components/detail-panel";
import { StageTracker } from "@/components/stage-tracker";
import { Accordion, Spinner } from "@/components/ui";
import { Select } from "@/components/forms";
import { FILTER_OPTIONS, getStageLabel } from "@/lib/constants";
import { formatCost, timeAgo } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { LayoutList, LayoutGrid, Play, AlertCircle } from "lucide-react";

// Pipeline stage buttons configuration
const PIPELINE_STAGES = [
  { id: "research", label: "Research", status: "idea_logged" },
  { id: "script", label: "Script", status: "ready_for_scripting" },
  { id: "voice", label: "Voice", status: "ready_for_voice" },
  { id: "prompts", label: "Prompts", status: "ready_for_prompts" },
  { id: "images", label: "Images", status: "ready_for_images" },
  { id: "thumbnail", label: "Thumbnail", status: "ready_for_thumbnail" },
  { id: "render", label: "Render", status: "ready_for_render" },
] as const;

// Visual style options
const VISUAL_STYLES = [
  { value: "cinematic_illustration", label: "Cinematic Illustration" },
  { value: "holographic_hud", label: "Holographic HUD" },
  { value: "cinematic_dossier", label: "Cinematic Dossier" },
  { value: "clay_mannequin", label: "Clay Mannequin" },
];

// Image model options
const IMAGE_MODELS = [
  { value: "z-image", label: "Z-Image (Default)" },
  { value: "Nano Banana", label: "Nano Banana" },
];

// Accent color options
const ACCENT_COLORS = [
  { value: "cold teal", label: "Cold Teal" },
  { value: "muted crimson", label: "Muted Crimson" },
  { value: "warm amber", label: "Warm Amber" },
  { value: "muted green", label: "Muted Green" },
];

export default function PipelinePage() {
  const [filter, setFilter] = useState("all");
  const [viewMode, setViewMode] = useState<"list" | "grid">("list");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: videos = [], isLoading } = useQuery({
    queryKey: ["videos", filter],
    queryFn: () => getVideos(filter === "all" ? undefined : filter),
  });

  const { data: selectedVideo } = useQuery({
    queryKey: ["video", selectedId],
    queryFn: () => getVideo(selectedId!),
    enabled: !!selectedId,
  });

  // Pipeline state
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [runningStage, setRunningStage] = useState<string | null>(null);

  // Run next step mutation
  const runNextMutation = useMutation({
    mutationFn: (id: string) => runNextStep(id),
    onMutate: () => {
      setPipelineRunning(true);
      setPipelineError(null);
      setRunningStage("next");
    },
    onSuccess: () => {
      // Start polling for completion
      pollTaskStatus();
    },
    onError: (error: Error) => {
      setPipelineRunning(false);
      setPipelineError(error.message);
      setRunningStage(null);
    },
  });

  // Run specific stage mutation
  const runStageMutation = useMutation({
    mutationFn: ({ videoId, stage }: { videoId: string; stage: string }) =>
      runPipelineStage(videoId, stage),
    onMutate: ({ stage }) => {
      setPipelineRunning(true);
      setPipelineError(null);
      setRunningStage(stage);
    },
    onSuccess: () => {
      pollTaskStatus();
    },
    onError: (error: Error) => {
      setPipelineRunning(false);
      setPipelineError(error.message);
      setRunningStage(null);
    },
  });

  // Poll for task completion
  const pollTaskStatus = async () => {
    if (!selectedId) return;

    const maxAttempts = 60; // 5 minutes with 5s intervals
    let attempts = 0;

    const poll = async () => {
      try {
        const status = await getPipelineTaskStatus(selectedId);

        if (status.status === "completed") {
          setPipelineRunning(false);
          setRunningStage(null);
          queryClient.invalidateQueries({ queryKey: ["videos"] });
          queryClient.invalidateQueries({ queryKey: ["video", selectedId] });
          return;
        }

        if (status.status === "failed") {
          setPipelineRunning(false);
          setPipelineError(status.error || "Pipeline stage failed");
          setRunningStage(null);
          return;
        }

        attempts++;
        if (attempts < maxAttempts) {
          setTimeout(poll, 5000);
        } else {
          setPipelineRunning(false);
          setPipelineError("Pipeline timed out");
          setRunningStage(null);
        }
      } catch {
        // If polling fails, just stop and let user retry
        setPipelineRunning(false);
        setRunningStage(null);
      }
    };

    setTimeout(poll, 2000); // Initial delay
  };

  // Reset pipeline state when video changes
  useEffect(() => {
    setPipelineRunning(false);
    setPipelineError(null);
    setRunningStage(null);
  }, [selectedId]);

  // Check if a stage button should be enabled
  const canRunStage = (stageStatus: string) => {
    if (!selectedVideo) return false;
    return selectedVideo.status === stageStatus;
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Pipeline</h1>
        <div className="flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-0.5">
          <button
            onClick={() => setViewMode("list")}
            className={cn(
              "rounded-md p-1.5",
              viewMode === "list" ? "bg-[var(--surface-elevated)]" : "text-[var(--text-secondary)]"
            )}
          >
            <LayoutList size={16} />
          </button>
          <button
            onClick={() => setViewMode("grid")}
            className={cn(
              "rounded-md p-1.5",
              viewMode === "grid" ? "bg-[var(--surface-elevated)]" : "text-[var(--text-secondary)]"
            )}
          >
            <LayoutGrid size={16} />
          </button>
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {FILTER_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            onClick={() => setFilter(opt.key)}
            className={cn(
              "flex-shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
              filter === opt.key
                ? "bg-[var(--accent)] text-black"
                : "bg-[var(--surface)] text-[var(--text-secondary)] hover:bg-[var(--surface-elevated)]"
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Loading skeletons */}
      {isLoading && (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-xl bg-[var(--surface)]" />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && videos.length === 0 && (
        <div className="flex h-40 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface)]">
          <p className="text-sm text-[var(--text-secondary)]">
            No videos{filter !== "all" ? ` in ${getStageLabel(filter)}` : ""}
          </p>
        </div>
      )}

      {/* List view */}
      {viewMode === "list" && (
        <div className="space-y-2">
          {videos.map((video) => (
            <VideoCard key={video.id} video={video} onClick={() => setSelectedId(video.id)} />
          ))}
        </div>
      )}

      {/* Grid view */}
      {viewMode === "grid" && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
          {videos.map((video) => (
            <button
              key={video.id}
              onClick={() => setSelectedId(video.id)}
              className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] text-left transition-colors hover:bg-[var(--surface-elevated)]"
            >
              <div className="aspect-video w-full bg-[var(--surface-elevated)]">
                {video.thumbnail_url ? (
                  <img src={video.thumbnail_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  <div
                    className="flex h-full w-full items-center justify-center text-2xl font-bold text-white/10"
                    style={{ background: `${video.accent_color}15` }}
                  >
                    {(video.video_title || "?").charAt(0)}
                  </div>
                )}
              </div>
              <div className="p-2.5">
                <p className="line-clamp-2 text-xs font-medium">{video.video_title || "Untitled"}</p>
                <div className="mt-1.5 flex items-center gap-2">
                  <span className="rounded-full bg-[var(--surface-elevated)] px-1.5 py-0.5 text-[9px] font-medium text-[var(--text-secondary)]">
                    {getStageLabel(video.status || "idea_logged")}
                  </span>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Detail panel */}
      <DetailPanel
        open={!!selectedId}
        onClose={() => setSelectedId(null)}
        title={selectedVideo?.video_title || undefined}
      >
        {selectedVideo && (
          <div className="space-y-6">
            {/* Thumbnail */}
            {selectedVideo.thumbnail_url && (
              <div className="aspect-video w-full overflow-hidden rounded-lg">
                <img src={selectedVideo.thumbnail_url} alt="" className="h-full w-full object-cover" />
              </div>
            )}

            {/* Stage tracker */}
            <div>
              <h3 className="mb-3 text-sm font-medium text-[var(--text-secondary)]">Progress</h3>
              <StageTracker status={selectedVideo.status || "idea_logged"} />
            </div>

            {/* Primary Action */}
            <div className="space-y-3">
              <button
                onClick={() => runNextMutation.mutate(selectedVideo.id)}
                disabled={pipelineRunning || selectedVideo.status === "done"}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-3 text-sm font-medium text-black transition-opacity disabled:opacity-50"
              >
                {pipelineRunning && runningStage === "next" ? (
                  <>
                    <Spinner size="sm" className="text-black" />
                    Running...
                  </>
                ) : (
                  <>
                    <Play size={16} />
                    Run Next Step
                  </>
                )}
              </button>

              {pipelineError && (
                <div className="flex items-center gap-2 rounded-lg bg-[var(--error)]/10 p-3 text-xs text-[var(--error)]">
                  <AlertCircle size={14} />
                  {pipelineError}
                </div>
              )}
            </div>

            {/* Advanced Pipeline Controls */}
            <Accordion title="Advanced Pipeline Controls">
              <div className="grid grid-cols-3 gap-2">
                {PIPELINE_STAGES.map((stage) => (
                  <button
                    key={stage.id}
                    onClick={() =>
                      runStageMutation.mutate({ videoId: selectedVideo.id, stage: stage.id })
                    }
                    disabled={pipelineRunning || !canRunStage(stage.status)}
                    className={cn(
                      "rounded-lg px-3 py-2 text-xs font-medium transition-colors",
                      canRunStage(stage.status)
                        ? "bg-[var(--surface-elevated)] hover:bg-[var(--accent)] hover:text-black"
                        : "bg-[var(--surface)] text-[var(--text-secondary)] opacity-50",
                      pipelineRunning &&
                        runningStage === stage.id &&
                        "bg-[var(--accent)] text-black"
                    )}
                  >
                    {pipelineRunning && runningStage === stage.id ? (
                      <Spinner size="sm" className="mx-auto" />
                    ) : (
                      stage.label
                    )}
                  </button>
                ))}
              </div>
              <p className="mt-3 text-xs text-[var(--text-secondary)]">
                Only the stage matching the current status is enabled.
              </p>
            </Accordion>

            {/* Style Overrides */}
            <Accordion title="Style Overrides">
              <div className="space-y-4">
                <Select
                  label="Visual Style"
                  options={VISUAL_STYLES}
                  value={selectedVideo.visual_style || "cinematic_illustration"}
                  onChange={() => {}}
                  helperText="Rendering style for generated images"
                />
                <Select
                  label="Image Model"
                  options={IMAGE_MODELS}
                  value="z-image"
                  onChange={() => {}}
                  helperText="AI model for image generation"
                />
                <Select
                  label="Accent Color"
                  options={ACCENT_COLORS}
                  value={selectedVideo.accent_color || "cold teal"}
                  onChange={() => {}}
                  helperText="Color theme for the video"
                />
                <p className="text-xs text-[var(--text-secondary)]">
                  Style override updates coming soon.
                </p>
              </div>
            </Accordion>

            {/* Metadata */}
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Cost</span>
                <span>{formatCost(selectedVideo.total_cost)}</span>
              </div>
              {selectedVideo.views > 0 && (
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">Views</span>
                  <span>{selectedVideo.views.toLocaleString()}</span>
                </div>
              )}
              {selectedVideo.ctr !== null && (
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">CTR</span>
                  <span>{selectedVideo.ctr}%</span>
                </div>
              )}
              {selectedVideo.visual_style && (
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">Visual Style</span>
                  <span>{selectedVideo.visual_style}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Updated</span>
                <span>{timeAgo(selectedVideo.updated_at)}</span>
              </div>
            </div>
          </div>
        )}
      </DetailPanel>
    </div>
  );
}
