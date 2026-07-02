"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { motion } from "framer-motion";
import {
  ArrowLeft, FileText, Image as ImageIcon, Film,
  BarChart3, Search, Video, Upload, Loader2, Brain, Volume2, Download, ExternalLink, X,
  Users, MoreHorizontal, MapPin, MessageCircle, Palette, Zap,
} from "lucide-react";
import { ChatCore } from "@/components/chat/ChatCore";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getVideo, getVideoAssets, getVideoActions, runBuild, resetPipeline, runNextStep, advanceVideo, clearStaleTask, getExportManifest, type ExportManifest } from "@/lib/api";
import { clipCost, CLIP_COST_PER_MODEL } from "@/lib/next-action";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import { StatusPill } from "@/components/ui/StatusPill";
import { PipelineStepper } from "@/components/production/PipelineStepper";
import { usePipelineSSE } from "@/hooks/use-pipeline-sse";
import { ResearchTab } from "@/components/production/ResearchTab";
import { CharactersTab } from "@/components/production/CharactersTab";
import { EnvironmentsTab } from "@/components/production/EnvironmentsTab";
import { GuidedNextStep } from "@/components/production/GuidedNextStep";
import { ScriptVoiceTab } from "@/components/production/ScriptVoiceTab";
import { ScenesWorkspaceTab } from "@/components/production/ScenesWorkspaceTab";
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
  { id: "research", label: "1 · Research", icon: Search },
  { id: "script-voice", label: "2 · Script & Voice", icon: FileText },
  { id: "characters", label: "3 · Characters", icon: Users },
  { id: "environments", label: "4 · Environments", icon: MapPin },
  { id: "scenes", label: "5 · Scenes", icon: Video },
  { id: "sound", label: "6 · Sound", icon: Volume2 },
  { id: "thumbnail", label: "7 · Thumbnail", icon: Film },
  { id: "render", label: "8 · Finish", icon: Film },
  { id: "upload", label: "9 · Upload", icon: Upload },
  { id: "performance", label: "10 · Results", icon: BarChart3 },
];

/** The old Storyboard and Video Clips tabs collapsed into Scenes (Ryan's
 * answer 1) — stored prefs and getNextAction keys may still say the old ids. */
const LEGACY_TAB_IDS: Record<string, string> = {
  "storyboard-visuals": "scenes",
  clips: "scenes",
};

/** Which pipeline-plan stage(s) a tab belongs to. A tab is shown when the
 * video's plan includes ANY of these stages. Videos with no plan (the full
 * pipeline — every existing video) show all tabs. Characters/Environments/Scenes
 * are all part of building the visuals (the "images"/"video" stages). */
const TAB_STAGES: Record<string, string[]> = {
  research: ["research"],
  "script-voice": ["script", "voice"],
  characters: ["images"],
  environments: ["images"],
  scenes: ["images", "video"],
  sound: ["sound"],
  thumbnail: ["thumbnail"],
  render: ["render"],
  upload: ["upload"],
  performance: ["upload"],
};

function tabVisible(tabId: string, plan: string[] | null | undefined): boolean {
  if (!plan || plan.length === 0) return true; // full pipeline → show everything
  const stages = TAB_STAGES[tabId];
  if (!stages) return true; // unknown tab → leave it visible
  return stages.some((s) => plan.includes(s));
}

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
  // Scenes owns everything from shot-planning through clip generation
  // (ready_for_video_generation = idx 15); thumbnail starts after.
  if (idx <= 15) return "scenes";
  if (idx <= 16) return "thumbnail";
  if (idx <= 19) return "render";
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

  // Live generation-cost estimate from what's actually been made (pictures + clips
  // dominate). The backend never rolls up videos.total_cost, so the counter sat at
  // $0.00 — compute it from the artifacts instead. Shares the cached assets query.
  // ponytail: an estimate from counts, not a per-API-call ledger.
  const { data: costAssets } = useQuery({
    queryKey: ["video-assets", videoId],
    queryFn: () => getVideoAssets(videoId),
    refetchInterval: () => (status && !TERMINAL_STATUSES.has(status) ? 5000 : false),
  });
  // Shared action layer: server-computed verbs, costs, and the build target.
  // This is the same registry chat's confirm cards read — one price list.
  const { data: videoActions } = useQuery({
    queryKey: ["video-actions", videoId],
    queryFn: () => getVideoActions(videoId),
    refetchInterval: () => (status && !TERMINAL_STATUSES.has(status) ? 10000 : false),
  });
  // Keep the local price table in lockstep with the server's (it's only the
  // offline fallback — the server is the source of truth).
  useEffect(() => {
    if (videoActions?.prices?.clip) Object.assign(CLIP_COST_PER_MODEL, videoActions.prices.clip);
  }, [videoActions?.prices?.clip]);
  const estimatedCost = useMemo(() => {
    // Prefer the server's spend figure (same formula chat quotes); fall back to
    // the local artifact count while the actions query is in flight.
    if (videoActions?.summary?.spent != null) return videoActions.summary.spent;
    const a = costAssets ?? [];
    const pictures = a.filter((x) => x.image_url).length;
    const clips = a.filter((x) => x.video_clip_url).length;
    return pictures * 0.08 + clipCost(video?.video_model, clips);
  }, [videoActions?.summary?.spent, costAssets, video?.video_model]);

  // Per-video plan: hide the tabs for steps the creator switched off. No plan
  // (full pipeline / every existing video) → all tabs show, unchanged.
  const planStages = (video?.pipeline_stages as string[] | null) ?? null;
  const visibleTabs = TABS.filter((t) => tabVisible(t.id, planStages));
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);

  // SSE for live pipeline updates (filtered to this video)
  // Refresh every tab's data on a stage change OR any task completion — including
  // tasks the CO-PILOT DOCK starts (e.g. "regenerate the script"), which the page's
  // own task poller doesn't watch. Without this the script/pictures show stale until
  // a manual page refresh.
  const refreshVideoData = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["video", videoId] });
    queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
    queryClient.invalidateQueries({ queryKey: ["segments", videoId] });
  }, [queryClient, videoId]);
  usePipelineSSE({
    enabled: !TERMINAL_STATUSES.has(status),
    videoId,
    onStageChange: (event) => {
      setLiveStatus(event.to_status);
      refreshVideoData();
    },
    onTaskProgress: (event) => {
      if (event.status === "completed") refreshVideoData();
    },
  });
  const [resetting, setResetting] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [showBuildConfirm, setShowBuildConfirm] = useState(false);
  const [buildStarting, setBuildStarting] = useState(false);
  const [runningNext, setRunningNext] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);
  const [approvalMessage, setApprovalMessage] = useState<string | null>(null);

  // Co-pilot dock/drawer: desktop gets the right panel; mobile gets a bottom
  // drawer. Same video-scoped ChatCore so the co-pilot is present on every page.
  // Remembers open/closed (read on the client to avoid an SSR localStorage access).
  const [dockOpen, setDockOpen] = useState(false);
  useEffect(() => {
    try { setDockOpen(localStorage.getItem("se_pipeline_chat_open") === "1"); } catch { /* private mode */ }
  }, []);
  const toggleDock = () =>
    setDockOpen((o) => {
      const next = !o;
      try { localStorage.setItem("se_pipeline_chat_open", next ? "1" : "0"); } catch { /* private mode */ }
      return next;
    });

  useTaskPoller({
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

  const rawTab = activeTab || defaultTab;
  const resolvedTab = LEGACY_TAB_IDS[rawTab] ?? rawTab;
  // If the resolved tab is hidden by the plan, land on the first visible tab.
  const currentTab = visibleTabs.some((t) => t.id === resolvedTab)
    ? resolvedTab
    : (visibleTabs[0]?.id ?? resolvedTab);

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
    <div
      className="lg:grid lg:gap-6 transition-[grid-template-columns] duration-300 ease-out"
      style={{ gridTemplateColumns: dockOpen ? "minmax(0, 1fr) 420px" : "minmax(0, 1fr) 0px" }}
    >
    <motion.div className="space-y-6 min-w-0" variants={container} initial="hidden" animate="show">
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
            {(() => {
              // Show the visual style so the creator sees what look the video uses.
              // A preset id -> friendly label; otherwise the detected style's first
              // clause. visual_style empty + image_style_override set == modeled
              // (the look was detected from the reference video, not picked).
              const PRESET: Record<string, string> = {
                pixar_3d: "Pixar 3D", flat_2d: "2D Flat", realistic: "Realistic",
                anime: "Anime", watercolor: "Watercolor", comic: "Comic",
              };
              const vs = (video.visual_style || "").trim();
              const iso = (video.image_style_override || "").trim();
              const label = vs ? (PRESET[vs] || vs) : (iso ? iso.split(/[.,;]/)[0].trim() : "");
              if (!label) return null;
              const fromRef = !vs && !!iso;
              return (
                <span
                  className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full"
                  style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
                  title={iso || label}
                >
                  <Palette size={11} /> {label}{fromRef ? " · from reference" : ""}
                </span>
              );
            })()}
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
              Est. Cost
            </p>
            <p className="text-lg font-mono font-semibold" style={{ color: "var(--gold)" }}>
              ${Math.max(video.total_cost || 0, estimatedCost).toFixed(2)}
            </p>
          </div>

          {/* Build button — the autobuild chainer chat's "build it" uses,
              now one tap from the page (PARITY-PLAN Phase 3). Cost + target
              come from the shared action layer, same numbers chat quotes. */}
          {videoActions && !TERMINAL_STATUSES.has(status) && (() => {
            const buildInfo = videoActions.actions.find((a) => a.verb === "build");
            const toPictures = videoActions.build_target === "pictures";
            const label = toPictures ? "Build to pictures" : "Finish the video";
            const detail = toPictures
              ? "Runs research, script, and the pictures, then stops for your review."
              : "Runs voice, clips, thumbnail, and the final render.";
            return (
              <div className="relative">
                <button
                  onClick={() => setShowBuildConfirm((o) => !o)}
                  disabled={taskRunning || buildStarting}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold transition-all active:scale-[0.98] disabled:opacity-40"
                  style={{ background: "var(--gold)", color: "var(--bg-void)" }}
                  title={detail}
                >
                  <Zap size={16} /> {label}
                </button>
                {showBuildConfirm && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setShowBuildConfirm(false)} />
                    <div
                      className="absolute right-0 top-full mt-2 z-50 w-72 rounded-xl p-4 space-y-3"
                      style={{ background: "var(--bg-deep)", border: "1px solid var(--border)", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}
                    >
                      <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{label}</p>
                      <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>{detail}</p>
                      <p className="text-xs font-mono" style={{ color: "var(--gold)" }}>
                        {buildInfo?.cost_text ? `Estimated: ${buildInfo.cost_text}` : ""}
                      </p>
                      <button
                        onClick={async () => {
                          setBuildStarting(true);
                          setShowBuildConfirm(false);
                          try {
                            await runBuild(videoId, videoActions.build_target);
                            setTaskRunning(true);
                            toast.info(`${label} started — follow along in the tracker.`);
                          } catch (e) {
                            toast.error(e instanceof Error ? e.message : "Couldn't start the build.");
                          } finally {
                            setBuildStarting(false);
                          }
                        }}
                        disabled={buildStarting}
                        className="w-full py-2 rounded-lg text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-40"
                        style={{ background: "var(--gold)", color: "var(--bg-void)" }}
                      >
                        {buildStarting ? "Starting…" : `Run it${buildInfo?.cost_text && buildInfo.cost !== 0 ? ` · ${buildInfo.cost_text}` : ""}`}
                      </button>
                    </div>
                  </>
                )}
              </div>
            );
          })()}

          {/* Co-pilot chat toggle (desktop). Slides the dock in/out. */}
          <button
            onClick={toggleDock}
            className="hidden lg:inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all active:scale-[0.98]"
            style={dockOpen
              ? { background: "var(--turquoise)", color: "var(--bg-void)" }
              : { background: "var(--bg-surface)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}
            title="Chat with the co-pilot about this video"
          >
            <MessageCircle size={16} /> Chat
          </button>

          {/* Advanced menu — everything power-user lives here, the big banner
              button below is the ONLY primary action on the page. */}
          <div className="relative">
            <button
              onClick={() => setShowResetConfirm(!showResetConfirm)}
              className="p-2 rounded-lg transition-all hover:bg-[var(--bg-surface)]"
              style={{ color: "var(--text-tertiary)" }}
              title="Advanced options"
            >
              <MoreHorizontal size={18} />
            </button>

            {showResetConfirm && (
              <>
              <div className="fixed inset-0 z-40" onClick={() => setShowResetConfirm(false)} />
              <div
                className="absolute right-0 top-full mt-2 z-50 w-64 rounded-xl p-2 space-y-0.5"
                style={{ background: "var(--bg-deep)", border: "1px solid var(--border)", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}
              >
                <p className="text-[10px] uppercase tracking-wider font-semibold px-3 pt-2 pb-1" style={{ color: "var(--text-tertiary)" }}>Advanced</p>
                <button
                  onClick={() => { setShowResetConfirm(false); handleExport(); }}
                  disabled={exportLoading}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[var(--bg-surface)] flex items-center gap-2"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {exportLoading ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                  Export assets
                </button>
                <button
                  onClick={() => { setShowResetConfirm(false); handleRunNext(); }}
                  disabled={runningNext || taskRunning}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[var(--bg-surface)] disabled:opacity-40"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Force-run next stage
                </button>
                <button
                  onClick={() => { setShowResetConfirm(false); handleSkipStage(); }}
                  disabled={skipping}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[var(--bg-surface)] disabled:opacity-40"
                  style={{ color: "var(--orange)" }}
                >
                  Skip this stage <span style={{ color: "var(--text-tertiary)" }}>— no checks</span>
                </button>
                <div className="mx-3 my-1 h-px" style={{ background: "var(--border-subtle)" }} />
                <p className="text-[10px] uppercase tracking-wider font-semibold px-3 pt-1 pb-1" style={{ color: "var(--text-tertiary)" }}>Start over from…</p>
                <button
                  onClick={() => handleReset("ready_for_scripting")}
                  disabled={resetting}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[var(--bg-surface)]"
                  style={{ color: "var(--orange)" }}
                >
                  {resetting ? "Resetting..." : "Script"} <span style={{ color: "var(--text-tertiary)" }}>— delete scripts + images</span>
                </button>
                <button
                  onClick={() => handleReset("ready_for_voice")}
                  disabled={resetting}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[var(--bg-surface)]"
                  style={{ color: "var(--green)" }}
                >
                  Voice <span style={{ color: "var(--text-tertiary)" }}>— keep scripts, redo voice</span>
                </button>
                <button
                  onClick={() => handleReset("ready_for_images")}
                  disabled={resetting}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[var(--bg-surface)]"
                  style={{ color: "var(--purple)" }}
                >
                  Images <span style={{ color: "var(--text-tertiary)" }}>— keep scripts, redo images</span>
                </button>
              </div>
              </>
            )}
          </div>
        </div>
      </motion.div>

      {/* Progress stepper — passive, the banner below is the one place to act */}
      <motion.div variants={item}>
        <PipelineStepper status={status} liveStatus={liveStatus} planStages={planStages} />
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

      {/* Guided next step — the one big button that always knows what's next.
          Hidden on the Scenes tab: the workspace's own green command bar (status +
          "Animate everything") is the single banner there, so they don't stack. */}
      {currentTab !== "scenes" && (
        <GuidedNextStep video={videoForTabs} onNavigate={(t) => setActiveTab(t)} planStages={planStages} />
      )}

      {/* Tab navigation */}
      <motion.div variants={item}>
        <div className="flex gap-0.5 overflow-x-auto pb-1 -mx-2 px-2" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
          {visibleTabs.map((tab, idx) => {
            const isActive = currentTab === tab.id;
            const Icon = tab.icon;
            // Renumber for the visible set so a hidden step doesn't leave gaps
            // (e.g. a script-only video shows "1 · Script & Voice", not "2 ·").
            const label = `${idx + 1} · ${tab.label.replace(/^\d+\s*·\s*/, "")}`;
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
                {label}
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
        {currentTab === "script-voice" && <ScriptVoiceTab video={videoForTabs} onAdvanced={() => setActiveTab("scenes")} />}
        {currentTab === "characters" && <CharactersTab video={videoForTabs} onApproved={() => setActiveTab("environments")} />}
        {currentTab === "environments" && <EnvironmentsTab video={videoForTabs} onApproved={() => setActiveTab("scenes")} />}
        {currentTab === "scenes" && <ScenesWorkspaceTab video={videoForTabs} onGoToScriptVoice={() => setActiveTab("script-voice")} onGoToEnvironments={() => setActiveTab("environments")} onGoToCharacters={() => setActiveTab("characters")} onAdvanced={() => setActiveTab("sound")} />}
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

      {/* Co-pilot dock — slides in from the right; page content reflows on desktop.
          Mobile uses the bottom drawer below. Live progress is free: the page's
          5s poll + SSE + task poller already reflect any work it kicks off. */}
      <aside className="hidden lg:block overflow-hidden">
        {dockOpen && (
          <div
            className="sticky top-4 w-[420px] flex flex-col rounded-2xl overflow-hidden"
            style={{ height: "calc(100vh - 2rem)", background: "var(--bg-deep)", border: "1px solid var(--border)" }}
          >
            <div className="flex items-center justify-between px-4 py-3 shrink-0" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2">
                <MessageCircle size={16} style={{ color: "var(--turquoise)" }} />
                <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Co-pilot</span>
              </div>
              <button
                onClick={toggleDock}
                className="p-1 rounded-lg transition-all hover:bg-[var(--bg-surface)]"
                style={{ color: "var(--text-tertiary)" }}
                aria-label="Close chat"
              >
                <X size={16} />
              </button>
            </div>
            <div className="flex-1 min-h-0">
              <ChatCore videoId={videoId} docked uiContext={{ tab: rawTab }} />
            </div>
          </div>
        )}
      </aside>

      {/* Mobile co-pilot drawer — phone access to the same video-scoped co-pilot. */}
      <button
        onClick={toggleDock}
        className="lg:hidden fixed bottom-24 right-5 z-[70] h-14 w-14 rounded-full flex items-center justify-center shadow-2xl active:scale-95 transition-transform"
        style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        aria-label={dockOpen ? "Close video co-pilot" : "Open video co-pilot"}
      >
        {dockOpen ? <X size={22} /> : <MessageCircle size={22} />}
      </button>

      {dockOpen && (
        <div className="lg:hidden fixed inset-0 z-[80] flex items-end" role="dialog" aria-modal="true" aria-label="Co-pilot">
          <button
            onClick={toggleDock}
            className="absolute inset-0 bg-black/60"
            aria-label="Close co-pilot overlay"
          />
          <div
            className="relative z-10 w-full h-[82vh] rounded-t-3xl overflow-hidden flex flex-col shadow-2xl"
            style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
          >
            <div className="flex items-center justify-between px-4 py-3 shrink-0" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2">
                <MessageCircle size={16} style={{ color: "var(--turquoise)" }} />
                <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Co-pilot</span>
              </div>
              <button
                onClick={toggleDock}
                className="p-2 rounded-xl transition-all hover:bg-[var(--bg-surface)]"
                style={{ color: "var(--text-tertiary)" }}
                aria-label="Close chat"
              >
                <X size={18} />
              </button>
            </div>
            <div className="flex-1 min-h-0">
              <ChatCore videoId={videoId} docked uiContext={{ tab: rawTab }} />
            </div>
          </div>
        </div>
      )}
    </div>
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
