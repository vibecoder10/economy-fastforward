"use client";

import { useState, useMemo } from "react";
import { useParams } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowLeft, FileText, Mic, Image as ImageIcon, LayoutGrid, Film, BarChart3 } from "lucide-react";
import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ProgressStepper } from "@/components/ui/ProgressStepper";
import { ScriptTab } from "@/components/production/ScriptTab";
import { VoiceReviewTab } from "@/components/production/VoiceReviewTab";
import { VisualsTab } from "@/components/production/VisualsTab";
import { StoryboardTab } from "@/components/production/StoryboardTab";
import { RenderTab } from "@/components/production/RenderTab";
import { PerformanceTab } from "@/components/production/PerformanceTab";
import { MOCK_VIDEOS } from "@/lib/mock-data";

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
  researching: { label: "Researching", color: "turquoise" },
  scripting: { label: "Scripting", color: "orange" },
  voice: { label: "Voice Generation", color: "green" },
  visuals: { label: "Generating Visuals", color: "purple" },
  storyboard_review: { label: "Storyboard Review", color: "turquoise" },
  rendering: { label: "Rendering", color: "red" },
  uploaded: { label: "Uploaded", color: "gold" },
  published: { label: "Published", color: "green" },
  done: { label: "Published", color: "green" },
};

const PIPELINE_STAGES = [
  "researching", "scripting", "voice", "visuals", "storyboard_review", "rendering",
];

const TABS = [
  { id: "script", label: "Script", icon: FileText },
  { id: "voice", label: "Voice & Storyboard", icon: Mic },
  { id: "visuals", label: "Visuals", icon: ImageIcon },
  { id: "storyboard", label: "Storyboard", icon: LayoutGrid },
  { id: "render", label: "Render", icon: Film },
  { id: "performance", label: "Performance", icon: BarChart3 },
];

function getStepFromStatus(status: string): number {
  const idx = PIPELINE_STAGES.indexOf(status);
  return idx >= 0 ? idx + 1 : status === "done" || status === "uploaded" || status === "published" ? 7 : 1;
}

function getCompletedSteps(status: string): number[] {
  const current = getStepFromStatus(status);
  return Array.from({ length: Math.min(current - 1, 6) }, (_, i) => i + 1);
}

function getDefaultTab(status: string): string {
  if (status === "scripting") return "script";
  if (status === "voice" || status === "storyboard_review") return "voice";
  if (status === "visuals") return "visuals";
  if (status === "rendering") return "render";
  if (status === "done" || status === "uploaded" || status === "published") return "performance";
  return "script";
}

export default function VideoDetailPage() {
  const params = useParams();
  const videoId = params.videoId as string;
  const video = MOCK_VIDEOS.find((v) => v.id === videoId) || MOCK_VIDEOS[4];

  const defaultTab = useMemo(() => getDefaultTab(video.status), [video.status]);
  const [activeTab, setActiveTab] = useState(defaultTab);

  const pill = STATUS_PILL[video.status] || { label: video.status, color: "turquoise" };
  const currentStep = getStepFromStatus(video.status);
  const completedSteps = getCompletedSteps(video.status);

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
            &ldquo;{video.title}&rdquo;
          </h1>
          <div className="flex items-center gap-3 flex-wrap">
            <StatusPill label={pill.label} color={pill.color} pulse size="md" />
            {video.framework && (
              <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                {video.framework}
              </span>
            )}
            {video.videoLengthMin && (
              <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                {video.videoLengthMin} min
              </span>
            )}
          </div>
        </div>
        <div className="text-right">
          <p className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
            Est. Cost
          </p>
          <p className="text-lg font-mono font-semibold" style={{ color: "var(--gold)" }}>
            ${(video.estimatedCost || 0).toFixed(2)}
          </p>
        </div>
      </motion.div>

      {/* Progress stepper */}
      <motion.div variants={item}>
        <ProgressStepper steps={6} currentStep={Math.min(currentStep, 6)} completedSteps={completedSteps} />
      </motion.div>

      {/* Tab navigation */}
      <motion.div variants={item}>
        <div className="flex gap-1 overflow-x-auto pb-1" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium font-body whitespace-nowrap transition-all rounded-t-lg"
                style={{
                  color: isActive ? "var(--turquoise)" : "var(--text-tertiary)",
                  background: isActive ? "var(--turquoise-bg)" : "transparent",
                  borderBottom: isActive ? "2px solid var(--turquoise)" : "2px solid transparent",
                }}
              >
                <Icon size={16} />
                {tab.label}
              </button>
            );
          })}
        </div>
      </motion.div>

      {/* Tab content */}
      <motion.div variants={item}>
        {activeTab === "script" && <ScriptTab video={video} />}
        {activeTab === "voice" && <VoiceReviewTab video={video} />}
        {activeTab === "visuals" && <VisualsTab video={video} />}
        {activeTab === "storyboard" && <StoryboardTab video={video} />}
        {activeTab === "render" && <RenderTab video={video} />}
        {activeTab === "performance" && <PerformanceTab video={video} />}
      </motion.div>
    </motion.div>
  );
}
