"use client";

import { motion } from "framer-motion";
import { Image as ImageIcon, Video, Mic, Volume2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { ActionButton } from "@/components/ui/ActionButton";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { MOCK_RENDER_STATE } from "@/lib/mock-data";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const BLOCK_ICONS: Record<string, React.ElementType> = {
  image: ImageIcon,
  video: Video,
  voice: Mic,
  sound: Volume2,
};

export default function RenderPage() {
  const r = MOCK_RENDER_STATE;

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-4">
          <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
            Render Pipeline
          </h1>
          <StatusPill label="Rendering" color="red" pulse size="md" />
        </div>
        <ActionButton variant="warning" className="hidden sm:flex">
          Render Now
        </ActionButton>
      </motion.div>

      {/* Main: preview + sidebar */}
      <motion.div variants={item} className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6">
        {/* Video preview */}
        <div className="space-y-4">
          <GlassCard className="p-0 overflow-hidden">
            <div
              className="aspect-video relative flex items-center justify-center"
              style={{ background: "var(--bg-elevated)" }}
            >
              {/* Wireframe placeholder */}
              <svg width="80" height="60" viewBox="0 0 80 60" className="opacity-20">
                <rect x="5" y="8" width="50" height="40" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" />
                <line x1="5" y1="8" x2="15" y2="2" stroke="var(--text-tertiary)" strokeWidth="1.5" />
                <line x1="55" y1="8" x2="65" y2="2" stroke="var(--text-tertiary)" strokeWidth="1.5" />
                <line x1="55" y1="48" x2="65" y2="42" stroke="var(--text-tertiary)" strokeWidth="1.5" />
                <rect x="15" y="2" width="50" height="40" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" />
                <circle cx="40" cy="25" r="4" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" />
              </svg>

              {/* Progress ring overlay */}
              <div className="absolute inset-0 flex items-center justify-center">
                <ProgressRing value={r.progress} size={120} color="var(--red)" strokeWidth={6}>
                  <span className="text-2xl font-bold font-mono" style={{ color: "var(--red)" }}>
                    {r.progress}%
                  </span>
                </ProgressRing>
              </div>
            </div>
          </GlassCard>

          {/* Scene Composition Timeline */}
          <GlassCard className="p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>
              Scene Composition Timeline
            </h3>
            <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
              {r.scenes.map((block, i) => {
                const Icon = BLOCK_ICONS[block.type] || ImageIcon;
                return (
                  <div
                    key={i}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg shrink-0"
                    style={{
                      background: `color-mix(in srgb, ${block.color} 15%, transparent)`,
                      border: `1px solid color-mix(in srgb, ${block.color} 25%, transparent)`,
                    }}
                  >
                    <Icon size={12} style={{ color: block.color }} />
                    {block.label && (
                      <span className="text-[11px] font-medium" style={{ color: block.color }}>
                        {block.label}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </GlassCard>

          {/* System resources */}
          <GlassCard className="p-4">
            <div className="flex items-center gap-6 text-xs font-mono flex-wrap">
              <span>
                RAM: <span style={{ color: "var(--turquoise)" }}>{r.ramUsage}</span>
              </span>
              <span>
                CPU load: <span style={{ color: "var(--turquoise)" }}>{r.cpuLoad}</span>
              </span>
              <span>
                Time remaining: <span style={{ color: "var(--gold)" }}>{r.timeRemaining}</span>
              </span>
            </div>
          </GlassCard>
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          <GlassCard className="p-5">
            <div className="space-y-3">
              {[
                { label: "Resolution", value: r.resolution },
                { label: "FPS", value: String(r.fps) },
                { label: "Duration", value: r.duration },
              ].map((row) => (
                <div key={row.label} className="flex items-center justify-between">
                  <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{row.label}</span>
                  <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>{row.value}</span>
                </div>
              ))}
            </div>

            <div className="mt-4 space-y-3">
              <FilterSelect
                label="Music Track"
                options={[
                  { value: "tension-rising", label: "Tension Rising - Cinematic" },
                  { value: "dark-ambient", label: "Dark Ambient" },
                  { value: "none", label: "No Music" },
                ]}
                value="tension-rising"
                onChange={() => {}}
              />
              <FilterSelect
                label="Export Format"
                options={[
                  { value: "mp4-h264", label: "MP4 (H.264)" },
                  { value: "mp4-h265", label: "MP4 (H.265)" },
                  { value: "webm", label: "WebM (VP9)" },
                ]}
                value="mp4-h264"
                onChange={() => {}}
              />
            </div>
          </GlassCard>

          <div className="space-y-2">
            <ActionButton variant="warning" className="w-full">
              Render Now
            </ActionButton>
            <ActionButton variant="filled" className="w-full">
              Preview Draft
            </ActionButton>
            <button
              className="w-full py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110"
              style={{
                background: "transparent",
                color: "var(--gold)",
                border: "1px solid var(--gold)",
              }}
            >
              Upload to YouTube
            </button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
