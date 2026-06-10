"use client";

import { useState, useMemo } from "react";
import { useParams } from "next/navigation";
import { motion } from "framer-motion";
import {
  ArrowLeft, FileText, Image as ImageIcon, Film,
  BarChart3, Search, Video, Upload, Loader2, RotateCcw, Brain, Volume2, Download, ExternalLink, X,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getVideo, resetPipeline, runNextStep, advanceVideo, clearStaleTask, getExportManifest, type ExportManifest } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import { StatusPill } from "@/components/ui/StatusPill";
import { PipelineStepper } from "@/components/production/PipelineStepper";
import { usePipelineSSE } from "@/hooks/use-pipeline-sse";
import { ResearchTab } from "@/components/production/ResearchTab";
import { CharactersTab } from "@/components/production/CharactersTab";
import { ScriptVoiceTab } from "@/components/production/ScriptVoiceTab";
import { StoryboardVisualsTab } from "@/components/production/StoryboardVisualsTab";
import { VideoClipsTab } from "@/components/production/VideoClipsTab";
import { ThumbnailTab } from "@/components/production/ThumbnailTab";
import { RenderTab } from "@/components/production/RenderTab";
import { UploadTab } from "@/components/production/UploadTab";
import { PerformanceTab } from "@/components/production/PerformanceTab";
import { SoundTab } from "@/components/production/SoundTab";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const STATUS_PILL: Record<string, { label: string; color: string }> = {
  idea_logged: { label: "Idea Logged", color: "turquoise" },
  approved: { label: "Approved", color: "turquoise" },
  researching: { label: "Researching", color: "turquoise" },
  ready_for_scripting: { label: "Ready for Script", color: "orange" },
  scripting: { label: "Scripting", color: "orange" },
  ready_for_voice: { label: "Ready for Voice", color: "green" },
  voice: { label: "Voice Gen", color: "green" },
  ready_for_image_prompts: { label: "Image Prompts", color: "purple" },
  ready_for_images: { label: "Generating Images", color: "purple" },
  ready_for_storyboards: { label: "Storyboards", color: "turquoise" },
  ready_for_storyboard_images: { label: "Storyboard Images", color: "turquoise" },
  ready_for_sound_design: { label: "Sound Design", color: "gold" },
  ready_for_sound_effects: { label: "Sound Effects", color: "gold" },
  ready_for_video_scripts: { label: "Video Scripts", color: "purple" },
  ready_for_video_generation: { label: "Video Gen", color: "purple" },
  ready_for_thumbnail: { label: "Thumbnail", color: "orange" },
  ready_to_render: { label: "Ready to Render", color: "red" },
  rendering: { label: "Rendering", color: "red" },
  rendered: { label: "Rendered", color: "green" },
  uploaded: { label: "Uploaded", color: "green" },
  uploaded_draft: { label: "Draft", color: "gold" },
  published: { label: "Published", color: "green" },
  done: { label: "Published", color: "green" },
};

const PIPELINE_ORDER = [
  "idea_logged", "approved", "researching", "ready_for_scripting", "scripting",
  "ready_for_voice", "voice", "ready_for_image_prompts", "ready_for_images",
  "ready_for_storyboards", "ready_for_storyboard_images", "ready_for_storyboard_extraction",
  "ready_for_sound_design", "ready_for_sound_effects",
  "ready_for_video_scripts", "ready_for_video_generation",
  "ready_for_thumbnail", "ready_to_render", "rendering", "rendered",
  "uploaded", "uploaded_draft", "done",
];

const TABS = [
  { id: "research", label: "Research", icon: Search },
  { id: "script-voice", label: "Script", icon: FileText },
  { id: "characters", label: "Characters", icon: Users },
  { id: "storyboard-visuals", label: "Storyboard & Visuals", icon: ImageIcon },
  { id: "clips", label: "Video Clips", icon: Video },
  { id: "sound", label: "Sound", icon: Volume2 },
  { id: "thumbnail", label: "Thumbnail", icon: Film },
  { id: "render", label: "Render", icon: Film },
  { id: "upload", label: "Upload", icon: Upload },
  { id: "performance", label: "Performance", icon: BarChart3 },
];

function parseInjectedLearnings(writerGuidance: string | null | undefined): { use: string[]; avoid: string[] } {
  if (!writerGuidance) return { use: [], avoid: [] };
  const match = writerGuidance.match(/--- PERFORMANCE LEARNINGS.*?---\n([\s\S]*?)--- END LEARNINGS ---/);
  if (!match) return { use: [], avoid: [] };
  const lines = match[1].split("\n").filter((l) => l.trim().startsWith("- "));
  const use: string[] = [];
  const avoid: string[] = [];
  for (const line of lines) {
    const cleaned = line.replace(/^- (USE|AVOID): /, "").trim();
    if (line.includes("- AVOID:")) avoid.push(cleaned);
    else use.push(cleaned);
  }
  return { use, avoid };
}

function getDefaultTab(status: string): string {
  const idx = PIPELINE_ORDER.indexOf(status);
  if (idx <= 2) return "research";
  if (idx <= 6) return "script-voice";
  if (idx <= 12) return "storyboard-visuals";
  if (idx <= 14) return "clips";
  if (idx <= 15) return "thumbnail";
  if (idx <= 18) return "render";
  return "performance";
}

export default function VideoDetailPage() {
  const params = useParams();
  const videoId = params.videoId as string;
  const queryClient = useQueryClient();
  const toast = useToast();

  const TERMINAL_STATUSES = new Set(["uploaded", "uploaded_draft", "done", "published"]);

  const { data: video, isLoading, error } = useQuery({
    queryKey: ["video", videoId],
    queryFn: () => getVideo(videoId),
    // Poll every 5s while pipeline is actively processing
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      if (!s || TERMINAL_STATUSES.has(s)) return false;
      return 5000;
    },
  });

  const status = video?.status || "idea_logged";
  const defaultTab = useMemo(() => getDefaultTab(status), [status]);
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);

  // SSE for live pipeline updates (filtered to this video)
  usePipelineSSE({
    enabled: !TERMINAL_STATUSES.has(status),
    videoId,
    onStageChange: (event) => {
      setLiveStatus(event.to_status);
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
    },
  });
  const [resetting, setResetting] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [runningNext, setRunningNext] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);
  const [approvalMessage, setApprovalMessage] = useState<string | null>(null);

  const { status: taskStatus, message: taskMessage, reset: resetTask } = useTaskPoller({
    videoId,
    enabled: taskRunning,
    interval: 3000,
    onComplete: (message) => {
      setTaskRunning(false);
      setRunningNext(false);
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
      // Show approval gate messages
      if (message && message.includes("needs approval")) {
        setApprovalMessage(message);
        setTimeout(() => setApprovalMessage(null), 8000);
      }
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setRunningNext(false);
      toast.error(`Pipeline step failed: ${error}`);
    },
  });

  // Export manifest state
  const [showExport, setShowExport] = useState(false);
  const [exportData, setExportData] = useState<ExportManifest | null>(null);
  const [exportLoading, setExportLoading] = useState(false);

  const handleExport = async () => {
    setExportLoading(true);
    try {
      const manifest = await getExportManifest(videoId);
      setExportData(manifest);
      setShowExport(true);
    } catch (err) {
      toast.error(`Export failed: ${(err as Error).message}`);
    } finally {
      setExportLoading(false);
    }
  };

  const downloadAsFile = (content: string, filename: string, type: string) => {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const currentTab = activeTab || defaultTab;

  const handleRunNext = async () => {
    setRunningNext(true);
    try {
      await runNextStep(videoId);
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(videoId);
          await runNextStep(videoId);
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          toast.error(`Run next step failed: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`Run next step failed: ${message}`);
      }
      setRunningNext(false);
    }
  };

  const handleSkipStage = async () => {
    setSkipping(true);
    try {
      await advanceVideo(videoId);
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
    } catch (err) {
      toast.error(`Skip stage failed: ${(err as Error).message}`);
    } finally {
      setSkipping(false);
    }
  };

  const handleReset = async (resetTo: string) => {
    setResetting(true);
    try {
      await resetPipeline(videoId, resetTo);
      // Invalidate all queries for this video to refetch fresh data
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
      setShowResetConfirm(false);
      setActiveTab("research");
    } catch (err) {
      toast.error(`Reset failed: ${(err as Error).message}`);
    } finally {
      setResetting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--turquoise)" }} />
      </div>
    );
  }

  if (error || !video) {
    return (
      <div className="space-y-4">
        <Link href="/pipeline" className="inline-flex items-center gap-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          <ArrowLeft size={16} /> Back to Videos
        </Link>
        <div className="glass-card p-8 text-center">
          <p style={{ color: "var(--red)" }}>Failed to load video: {(error as Error)?.message || "Not found"}</p>
        </div>
      </div>
    );
  }

  const pill = STATUS_PILL[status] || { label: status.replace(/_/g, " "), color: "turquoise" };

  // Build a normalized video object for tab components (they expect certain field names)
  // All field accesses use optional chaining to handle published videos that may lack pipeline fields
  const videoForTabs: any = {
    ...video,
    id: video?.id,
    title: video?.video_title || "Untitled",
    status: video?.status,
    framework: video?.framework_angle || video?.thematic_framework,
    videoLengthMin: video?.video_length_minutes,
    wordCount: video?.script ? video.script.split(/\s+/).length : 0,
    sceneCount: 0, // Will be populated from script endpoint
    estimatedCost: video?.total_cost ?? 0,
    views: video?.views ?? 0,
    ctr: video?.ctr ?? null,
    retention: video?.avg_retention ?? null,
    verdict: video?.performance_verdict ?? null,
    uploadDate: video?.created_at?.split("T")[0] ?? null,
    thumbnailUrl: video?.thumbnail_url ?? null,
  };

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      {/* Back */}
      <motion.div variants={item}>
        <Link
          href="/pipeline"
          className="inline-flex items-center gap-2 text-sm transition-colors hover:text-[var(--turquoise)]"
          style={{ color: "var(--text-secondary)" }}
        >
          <ArrowLeft size={16} />
          Back to Videos
        </Link>
      </motion.div>

      {/* Header */}
      <motion.div variants={item} className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-display mb-2" style={{ color: "var(--text-primary)" }}>
            &ldquo;{video.video_title || "Untitled"}&rdquo;
          </h1>
          <div className="flex items-center gap-3 flex-wrap">
            <StatusPill label={pill.label} color={pill.color} pulse size="md" />
            {(taskRunning || runningNext) && (
              <span className="flex items-center gap-1.5 text-[11px] font-mono" style={{ color: "var(--turquoise)" }}>
                <Loader2 size={10} className="animate-spin" />
                {taskMessage || "Pipeline running"}
              </span>
            )}
            {video.framework_angle && (
              <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                {video.framework_angle}
              </span>
            )}
            {video.video_length_minutes && (
              <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                {video.video_length_minutes} min
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
              Est. Cost
            </p>
            <p className="text-lg font-mono font-semibold" style={{ color: "var(--gold)" }}>
              ${(video.total_cost || 0).toFixed(2)}
            </p>
          </div>

          {/* Export button */}
          <button
            onClick={handleExport}
            disabled={exportLoading}
            className="p-2 rounded-lg transition-all hover:bg-[var(--bg-surface)]"
            style={{ color: "var(--text-tertiary)" }}
            title="Export assets"
          >
            {exportLoading ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
          </button>

          {/* Reset button */}
          <div className="relative">
            <button
              onClick={() => setShowResetConfirm(!showResetConfirm)}
              className="p-2 rounded-lg transition-all hover:bg-[var(--bg-surface)]"
              style={{ color: "var(--text-tertiary)" }}
              title="Reset pipeline"
            >
              <RotateCcw size={16} />
            </button>

            {showResetConfirm && (
              <div
                className="absolute right-0 top-full mt-2 z-50 w-56 rounded-xl p-4 space-y-2"
                style={{ background: "var(--bg-deep)", border: "1px solid var(--border)", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}
              >
                <p className="text-xs font-semibold mb-2" style={{ color: "var(--text-primary)" }}>Reset to:</p>
                <button
                  onClick={() => handleReset("ready_for_scripting")}
                  disabled={resetting}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[var(--bg-surface)]"
                  style={{ color: "var(--orange)" }}
                >
                  {resetting ? "Resetting..." : "Script Stage"} <span style={{ color: "var(--text-tertiary)" }}>— delete scripts + images</span>
                </button>
                <button
                  onClick={() => handleReset("ready_for_voice")}
                  disabled={resetting}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[var(--bg-surface)]"
                  style={{ color: "var(--green)" }}
                >
                  Voice Stage <span style={{ color: "var(--text-tertiary)" }}>— keep scripts, redo voice</span>
                </button>
                <button
                  onClick={() => handleReset("ready_for_images")}
                  disabled={resetting}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[var(--bg-surface)]"
                  style={{ color: "var(--purple)" }}
                >
                  Images Stage <span style={{ color: "var(--text-tertiary)" }}>— keep scripts, redo images</span>
                </button>
                <button
                  onClick={() => setShowResetConfirm(false)}
                  className="w-full text-xs px-3 py-1.5 rounded-lg mt-1"
                  style={{ color: "var(--text-tertiary)" }}
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        </div>
      </motion.div>

      {/* Progress stepper + pipeline controls */}
      <motion.div variants={item}>
        <div className="flex items-center justify-between gap-6">
          <PipelineStepper status={status} liveStatus={liveStatus} />
          <div className="flex items-center gap-3 shrink-0">
            <StatusPill label={pill.label} color={pill.color} pulse size="md" />
            <button
              onClick={handleRunNext}
              disabled={runningNext || taskRunning}
              className="px-4 py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              {(runningNext || taskRunning) ? <Loader2 size={14} className="animate-spin inline mr-1" /> : null}
              {taskRunning ? (taskMessage || "Running...") : runningNext ? "Starting..." : "Run Next Step"}
            </button>
            <button
              onClick={handleSkipStage}
              disabled={skipping}
              className="px-4 py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ background: "rgba(255, 120, 73, 0.15)", color: "var(--orange)", border: "1px solid var(--orange)" }}
            >
              {skipping ? <Loader2 size={14} className="animate-spin inline mr-1" /> : null}
              {skipping ? "Skipping..." : "Skip Stage"}
            </button>
          </div>
        </div>
      </motion.div>

      {/* Learnings applied indicator — only on Script tab */}
      {currentTab === "script-voice" && (() => {
        const injected = parseInjectedLearnings(video.writer_guidance);
        const total = injected.use.length + injected.avoid.length;
        if (total === 0) return null;
        return (
          <motion.div variants={item}>
            <div
              className="rounded-xl px-4 py-3"
              style={{
                background: "rgba(0, 245, 212, 0.04)",
                border: "1px solid rgba(0, 245, 212, 0.1)",
              }}
            >
              <div className="flex items-center gap-2 mb-2">
                <Brain size={14} style={{ color: "var(--turquoise)" }} />
                <span className="text-xs font-semibold" style={{ color: "var(--turquoise)" }}>
                  {total} Learning{total !== 1 ? "s" : ""} Applied to Script
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {injected.use.map((p, i) => (
                  <span
                    key={`use-${i}`}
                    className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full"
                    style={{
                      color: "var(--green)",
                      background: "rgba(0, 200, 83, 0.08)",
                      border: "1px solid rgba(0, 200, 83, 0.12)",
                    }}
                  >
                    USE: {p.length > 50 ? p.slice(0, 50) + "…" : p}
                  </span>
                ))}
                {injected.avoid.map((p, i) => (
                  <span
                    key={`avoid-${i}`}
                    className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full"
                    style={{
                      color: "var(--red)",
                      background: "rgba(255, 82, 82, 0.08)",
                      border: "1px solid rgba(255, 82, 82, 0.12)",
                    }}
                  >
                    AVOID: {p.length > 50 ? p.slice(0, 50) + "…" : p}
                  </span>
                ))}
              </div>
            </div>
          </motion.div>
        );
      })()}

      {/* Tab navigation */}
      <motion.div variants={item}>
        <div className="flex gap-0.5 overflow-x-auto pb-1 -mx-2 px-2" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
          {TABS.map((tab) => {
            const isActive = currentTab === tab.id;
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium font-body whitespace-nowrap transition-all rounded-t-lg shrink-0"
                style={{
                  color: isActive ? "var(--turquoise)" : "var(--text-tertiary)",
                  background: isActive ? "var(--turquoise-bg)" : "transparent",
                  borderBottom: isActive ? "2px solid var(--turquoise)" : "2px solid transparent",
                }}
              >
                <Icon size={14} />
                {tab.label}
              </button>
            );
          })}
        </div>
      </motion.div>

      {/* Approval gate message */}
      {approvalMessage && (
        <motion.div variants={item}>
          <div
            className="flex items-center gap-3 px-4 py-3 rounded-xl text-sm"
            style={{
              background: "rgba(255, 186, 8, 0.1)",
              border: "1px solid rgba(255, 186, 8, 0.2)",
              color: "var(--gold)",
            }}
          >
            <span className="shrink-0">⚠</span>
            <span>{approvalMessage}</span>
            <button
              onClick={() => setApprovalMessage(null)}
              className="ml-auto text-xs opacity-60 hover:opacity-100"
            >
              ✕
            </button>
          </div>
        </motion.div>
      )}

      {/* Tab content */}
      <motion.div variants={item}>
        {currentTab === "research" && <ResearchTab video={videoForTabs} onApproved={() => setActiveTab("script-voice")} />}
        {currentTab === "script-voice" && <ScriptVoiceTab video={videoForTabs} onAdvanced={() => setActiveTab("storyboard-visuals")} />}
        {currentTab === "characters" && <CharactersTab video={videoForTabs} onApproved={() => setActiveTab("storyboard-visuals")} />}
        {currentTab === "storyboard-visuals" && <StoryboardVisualsTab video={videoForTabs} onGoToScriptVoice={() => setActiveTab("script-voice")} onAdvanced={() => setActiveTab("clips")} />}
        {currentTab === "clips" && <VideoClipsTab video={videoForTabs} onAdvanced={() => setActiveTab("sound")} />}
        {currentTab === "sound" && <SoundTab video={videoForTabs} onAdvanced={() => setActiveTab("thumbnail")} />}
        {currentTab === "thumbnail" && <ThumbnailTab video={videoForTabs} onAdvanced={() => setActiveTab("render")} />}
        {currentTab === "render" && <RenderTab video={videoForTabs} onAdvanced={() => setActiveTab("upload")} />}
        {currentTab === "upload" && <UploadTab video={videoForTabs} onAdvanced={() => setActiveTab("performance")} />}
        {currentTab === "performance" && <PerformanceTab video={videoForTabs} />}
      </motion.div>
      {/* Export Modal */}
      {showExport && exportData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowExport(false)}>
          <div
            className="w-full max-w-lg rounded-2xl p-6 space-y-4"
            style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-display" style={{ color: "var(--text-primary)" }}>Export Assets</h2>
              <button onClick={() => setShowExport(false)} className="p-1" style={{ color: "var(--text-tertiary)" }}>
                <X size={18} />
              </button>
            </div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>{exportData.video_title}</p>

            <div className="space-y-2">
              {exportData.final_video_url && (
                <ExportRow label="Final Video (MP4)" onClick={() => window.open(exportData.final_video_url!, "_blank")} icon={<ExternalLink size={14} />} />
              )}
              {exportData.thumbnail_url && (
                <ExportRow label="Thumbnail" onClick={() => window.open(exportData.thumbnail_url!, "_blank")} icon={<ExternalLink size={14} />} />
              )}
              {exportData.drive_folder_link && (
                <ExportRow label="Google Drive Folder" onClick={() => window.open(exportData.drive_folder_link!, "_blank")} icon={<ExternalLink size={14} />} />
              )}
              {exportData.youtube_url && (
                <ExportRow label="YouTube" onClick={() => window.open(exportData.youtube_url!, "_blank")} icon={<ExternalLink size={14} />} />
              )}
              {exportData.voice_tracks.length > 0 && (
                <ExportRow
                  label={`Voice Tracks (${exportData.voice_tracks.length} scenes)`}
                  onClick={() => {
                    const text = exportData.voice_tracks.map((v) => `Scene ${v.scene}: ${v.voice_over_url}`).join("\n");
                    downloadAsFile(text, "voice-tracks.txt", "text/plain");
                  }}
                  icon={<Download size={14} />}
                />
              )}
              {exportData.assets.length > 0 && (
                <ExportRow
                  label={`Asset Manifest (${exportData.assets.length} images)`}
                  onClick={() => {
                    downloadAsFile(JSON.stringify(exportData.assets, null, 2), "assets.json", "application/json");
                  }}
                  icon={<Download size={14} />}
                />
              )}
              {!exportData.final_video_url && !exportData.thumbnail_url && exportData.assets.length === 0 && (
                <p className="text-xs py-4 text-center" style={{ color: "var(--text-tertiary)" }}>
                  No assets available yet. Complete more pipeline stages to generate downloadable files.
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}

function ExportRow({ label, onClick, icon }: { label: string; onClick: () => void; icon: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-between px-4 py-3 rounded-lg text-sm transition-all hover:brightness-110"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
    >
      {label}
      <span style={{ color: "var(--turquoise)" }}>{icon}</span>
    </button>
  );
}
