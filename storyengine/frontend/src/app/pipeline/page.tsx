"use client";

import { useState, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getVideos,
  getVideo,
  runNextStep,
  runPipelineStage,
  getPipelineTaskStatus,
  updateVideoStyles,
  type VideoSummary,
  type VideoDetail,
} from "@/lib/api";
import { VideoCard } from "@/components/video-card";
import { DetailPanel } from "@/components/detail-panel";
import { StageTracker } from "@/components/stage-tracker";
import { Accordion, Spinner } from "@/components/ui";
import { Select } from "@/components/forms";
import { getStageLabel } from "@/lib/constants";
import { formatCost, timeAgo } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { Play, AlertCircle, CheckCircle, Search, Plus } from "lucide-react";

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
  { value: "Nano Banana", label: "Nano Banana (Default)" },
  { value: "z-image", label: "Z-Image" },
];

// Accent color options
const ACCENT_COLORS = [
  { value: "cold teal", label: "Cold Teal" },
  { value: "muted crimson", label: "Muted Crimson" },
  { value: "warm amber", label: "Warm Amber" },
  { value: "muted green", label: "Muted Green" },
];

// Status filter options
const STATUS_FILTERS = [
  { value: "all", label: "All" },
  { value: "in_progress", label: "In Progress" },
  { value: "needs_approval", label: "Needs Approval" },
  { value: "done", label: "Done" },
];

// Sort options
const SORT_OPTIONS = [
  { value: "newest", label: "Newest" },
  { value: "oldest", label: "Oldest" },
  { value: "views", label: "Most Views" },
  { value: "ctr", label: "Highest CTR" },
];

// Statuses that count as "in progress"
const IN_PROGRESS_STATUSES = new Set([
  "ready_for_scripting",
  "ready_for_voice",
  "ready_for_storyboards",
  "ready_for_images",
  "ready_for_thumbnail",
  "ready_to_render",
  "rendered",
]);

// Statuses that count as "needs approval"
const NEEDS_APPROVAL_STATUSES = new Set([
  "ready_for_scripting",
  "ready_for_storyboards",
  "ready_for_thumbnail",
]);

export default function PipelinePage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortBy, setSortBy] = useState("newest");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  // Fetch all videos (no server-side filter — we filter client-side for the new categories)
  const { data: allVideos = [], isLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  const { data: selectedVideo } = useQuery({
    queryKey: ["video", selectedId],
    queryFn: () => getVideo(selectedId!),
    enabled: !!selectedId,
  });

  // Filter and sort videos client-side
  const videos = useMemo(() => {
    let filtered = [...allVideos];

    // Search filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter((v) =>
        (v.video_title || "").toLowerCase().includes(q)
      );
    }

    // Status filter
    if (statusFilter === "in_progress") {
      filtered = filtered.filter((v) => IN_PROGRESS_STATUSES.has(v.status || ""));
    } else if (statusFilter === "needs_approval") {
      filtered = filtered.filter((v) => NEEDS_APPROVAL_STATUSES.has(v.status || ""));
    } else if (statusFilter === "done") {
      filtered = filtered.filter((v) => v.status === "done" || v.status === "uploaded_draft");
    }

    // Sort
    if (sortBy === "newest") {
      filtered.sort((a, b) => {
        const da = a.created_at ? new Date(a.created_at).getTime() : 0;
        const db = b.created_at ? new Date(b.created_at).getTime() : 0;
        return db - da;
      });
    } else if (sortBy === "oldest") {
      filtered.sort((a, b) => {
        const da = a.created_at ? new Date(a.created_at).getTime() : 0;
        const db = b.created_at ? new Date(b.created_at).getTime() : 0;
        return da - db;
      });
    } else if (sortBy === "views") {
      filtered.sort((a, b) => (b.views || 0) - (a.views || 0));
    } else if (sortBy === "ctr") {
      filtered.sort((a, b) => (b.ctr ?? -1) - (a.ctr ?? -1));
    }

    return filtered;
  }, [allVideos, searchQuery, statusFilter, sortBy]);

  // Pipeline state
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [runningStage, setRunningStage] = useState<string | null>(null);

  // Style update state
  const [styleUpdateStatus, setStyleUpdateStatus] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [styleUpdateError, setStyleUpdateError] = useState<string | null>(null);

  // Run next step mutation
  const runNextMutation = useMutation({
    mutationFn: (id: string) => runNextStep(id),
    onMutate: () => {
      setPipelineRunning(true);
      setPipelineError(null);
      setRunningStage("next");
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

  // Style update mutation
  const styleUpdateMutation = useMutation({
    mutationFn: (styles: { visual_style?: string; accent_color?: string; image_model_override?: string }) =>
      updateVideoStyles(selectedId!, styles),
    onMutate: () => {
      setStyleUpdateStatus("saving");
      setStyleUpdateError(null);
    },
    onSuccess: () => {
      setStyleUpdateStatus("success");
      queryClient.invalidateQueries({ queryKey: ["video", selectedId] });
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      setTimeout(() => setStyleUpdateStatus("idle"), 2000);
    },
    onError: (error: Error) => {
      setStyleUpdateStatus("error");
      setStyleUpdateError(error.message);
    },
  });

  // Poll for task completion
  const pollTaskStatus = async () => {
    if (!selectedId) return;

    const maxAttempts = 60;
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
        setPipelineRunning(false);
        setRunningStage(null);
      }
    };

    setTimeout(poll, 2000);
  };

  // Reset pipeline state when video changes
  useEffect(() => {
    setPipelineRunning(false);
    setPipelineError(null);
    setRunningStage(null);
    setStyleUpdateStatus("idle");
    setStyleUpdateError(null);
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
        <a
          href="#"
          className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-opacity hover:opacity-90"
          style={{ backgroundColor: "var(--amber)", color: "var(--bg-primary)" }}
        >
          <Plus size={16} />
          New
        </a>
      </div>

      {/* Search */}
      <div className="relative">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]"
        />
        <input
          type="text"
          placeholder="Search videos..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-card)] py-2 pl-9 pr-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:ring-1 focus:ring-[var(--border)]"
        />
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--border)]"
        >
          {STATUS_FILTERS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--border)]"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
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
            {searchQuery
              ? `No videos matching "${searchQuery}"`
              : statusFilter !== "all"
                ? `No ${STATUS_FILTERS.find((f) => f.value === statusFilter)?.label ?? ""} videos`
                : "No videos"}
          </p>
        </div>
      )}

      {/* Video list */}
      <div className="space-y-2">
        {videos.map((video) => (
          <VideoCard key={video.id} video={video} onClick={() => setSelectedId(video.id)} />
        ))}
      </div>

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
                  onChange={(e) =>
                    styleUpdateMutation.mutate({ visual_style: e.target.value })
                  }
                  helperText="Rendering style for generated images"
                  disabled={styleUpdateStatus === "saving"}
                />
                <Select
                  label="Image Model"
                  options={IMAGE_MODELS}
                  value={selectedVideo.image_model_override || "Nano Banana"}
                  onChange={(e) =>
                    styleUpdateMutation.mutate({ image_model_override: e.target.value })
                  }
                  helperText="AI model for image generation"
                  disabled={styleUpdateStatus === "saving"}
                />
                <Select
                  label="Accent Color"
                  options={ACCENT_COLORS}
                  value={selectedVideo.accent_color || "cold teal"}
                  onChange={(e) =>
                    styleUpdateMutation.mutate({ accent_color: e.target.value })
                  }
                  helperText="Color theme for the video"
                  disabled={styleUpdateStatus === "saving"}
                />

                {/* Feedback */}
                {styleUpdateStatus === "saving" && (
                  <div className="flex items-center gap-2 rounded-lg bg-[var(--surface-elevated)] p-3 text-xs">
                    <Spinner size="sm" />
                    Saving...
                  </div>
                )}
                {styleUpdateStatus === "success" && (
                  <div className="flex items-center gap-2 rounded-lg bg-green-500/10 p-3 text-xs text-green-500">
                    <CheckCircle size={14} />
                    Style updated successfully
                  </div>
                )}
                {styleUpdateStatus === "error" && (
                  <div className="flex items-center gap-2 rounded-lg bg-[var(--error)]/10 p-3 text-xs text-[var(--error)]">
                    <AlertCircle size={14} />
                    {styleUpdateError || "Failed to update style"}
                  </div>
                )}
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
