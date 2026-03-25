"use client";

import { useState, useMemo } from "react";
import { useParams } from "next/navigation";
import { motion } from "framer-motion";
import {
  ArrowLeft, FileText, Mic, Image as ImageIcon, Film,
  BarChart3, Search, Video, Upload, Loader2, RotateCcw,
} from "lucide-react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getVideo, resetPipeline } from "@/lib/api";
import { StatusPill } from "@/components/ui/StatusPill";
import { ProgressStepper } from "@/components/ui/ProgressStepper";
import { ResearchTab } from "@/components/production/ResearchTab";
import { ScriptTab } from "@/components/production/ScriptTab";
import { VoiceReviewTab } from "@/components/production/VoiceReviewTab";
import { VisualsTab } from "@/components/production/VisualsTab";
import { VideoClipsTab } from "@/components/production/VideoClipsTab";
import { ThumbnailTab } from "@/components/production/ThumbnailTab";
import { RenderTab } from "@/components/production/RenderTab";
import { UploadTab } from "@/components/production/UploadTab";
import { PerformanceTab } from "@/components/production/PerformanceTab";

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
  "ready_for_storyboards", "ready_for_storyboard_images",
  "ready_for_sound_design", "ready_for_sound_effects",
  "ready_for_video_scripts", "ready_for_video_generation",
  "ready_for_thumbnail", "ready_to_render", "rendering", "rendered",
  "uploaded", "uploaded_draft", "done",
];

const TABS = [
  { id: "research", label: "Research", icon: Search },
  { id: "script", label: "Script", icon: FileText },
  { id: "voice", label: "Voice & Storyboard", icon: Mic },
  { id: "visuals", label: "Visuals", icon: ImageIcon },
  { id: "clips", label: "Video Clips", icon: Video },
  { id: "thumbnail", label: "Thumbnail", icon: Film },
  { id: "render", label: "Render", icon: Film },
  { id: "upload", label: "Upload", icon: Upload },
  { id: "performance", label: "Performance", icon: BarChart3 },
];

function getStepFromStatus(status: string): number {
  const idx = PIPELINE_ORDER.indexOf(status);
  if (idx < 0) return 1;
  // Map 22 statuses to 6 visual steps
  if (idx <= 2) return 1;   // Research
  if (idx <= 4) return 2;   // Script
  if (idx <= 6) return 3;   // Voice
  if (idx <= 12) return 4;  // Visuals/Sound
  if (idx <= 15) return 5;  // Video/Thumbnail
  return 6;                  // Render/Upload/Done
}

function getCompletedSteps(status: string): number[] {
  const current = getStepFromStatus(status);
  if (["uploaded", "uploaded_draft", "done", "published", "rendered"].includes(status)) {
    return [1, 2, 3, 4, 5, 6];
  }
  return Array.from({ length: Math.max(current - 1, 0) }, (_, i) => i + 1);
}

function getDefaultTab(status: string): string {
  const idx = PIPELINE_ORDER.indexOf(status);
  if (idx <= 2) return "research";
  if (idx <= 4) return "script";
  if (idx <= 6) return "voice";
  if (idx <= 12) return "visuals";
  if (idx <= 15) return "clips";
  if (idx <= 18) return "render";
  return "performance";
}

export default function VideoDetailPage() {
  const params = useParams();
  const videoId = params.videoId as string;
  const queryClient = useQueryClient();

  const { data: video, isLoading, error } = useQuery({
    queryKey: ["video", videoId],
    queryFn: () => getVideo(videoId),
  });

  const status = video?.status || "idea_logged";
  const defaultTab = useMemo(() => getDefaultTab(status), [status]);
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const currentTab = activeTab || defaultTab;

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
      alert(`Reset failed: ${(err as Error).message}`);
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
          <ArrowLeft size={16} /> Back to Queue
        </Link>
        <div className="glass-card p-8 text-center">
          <p style={{ color: "var(--red)" }}>Failed to load video: {(error as Error)?.message || "Not found"}</p>
        </div>
      </div>
    );
  }

  const pill = STATUS_PILL[status] || { label: status.replace(/_/g, " "), color: "turquoise" };
  const currentStep = getStepFromStatus(status);
  const completedSteps = getCompletedSteps(status);

  // Build a normalized video object for tab components (they expect certain field names)
  const videoForTabs: any = {
    ...video,
    id: video.id,
    title: video.video_title || "Untitled",
    status: video.status,
    framework: video.framework_angle || video.thematic_framework,
    videoLengthMin: video.video_length_minutes,
    wordCount: video.script ? video.script.split(/\s+/).length : 0,
    sceneCount: 0, // Will be populated from script endpoint
    estimatedCost: video.total_cost || 0,
    views: video.views,
    ctr: video.ctr,
    retention: video.avg_retention,
    verdict: video.performance_verdict,
    uploadDate: video.created_at?.split("T")[0],
    thumbnailUrl: video.thumbnail_url,
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
          Back to Queue
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

      {/* Progress stepper */}
      <motion.div variants={item}>
        <ProgressStepper steps={6} currentStep={Math.min(currentStep, 6)} completedSteps={completedSteps} />
      </motion.div>

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

      {/* Tab content */}
      <motion.div variants={item}>
        {currentTab === "research" && <ResearchTab video={videoForTabs} />}
        {currentTab === "script" && <ScriptTab video={videoForTabs} />}
        {currentTab === "voice" && <VoiceReviewTab video={videoForTabs} />}
        {currentTab === "visuals" && <VisualsTab video={videoForTabs} />}
        {currentTab === "clips" && <VideoClipsTab video={videoForTabs} />}
        {currentTab === "thumbnail" && <ThumbnailTab video={videoForTabs} />}
        {currentTab === "render" && <RenderTab video={videoForTabs} />}
        {currentTab === "upload" && <UploadTab video={videoForTabs} />}
        {currentTab === "performance" && <PerformanceTab video={videoForTabs} />}
      </motion.div>
    </motion.div>
  );
}
