"use client";

import { motion } from "framer-motion";
import { Film, TrendingUp, DollarSign, AlertTriangle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatCard } from "@/components/ui/StatCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { MOCK_VIDEOS, MOCK_ACTIVITY, PIPELINE_FUNNEL } from "@/lib/mock-data";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};

const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: "easeOut" as const } },
};

const publishedCount = MOCK_VIDEOS.filter((v) => v.status === "done").length;
const inProduction = MOCK_VIDEOS.filter((v) => v.status !== "done").length;
const avgCost =
  MOCK_VIDEOS.filter((v) => v.estimatedCost).reduce((sum, v) => sum + (v.estimatedCost || 0), 0) /
  MOCK_VIDEOS.filter((v) => v.estimatedCost).length;
const avgCtr =
  MOCK_VIDEOS.filter((v) => v.ctr).reduce((sum, v) => sum + (v.ctr || 0), 0) /
  MOCK_VIDEOS.filter((v) => v.ctr).length;

const upNext = MOCK_VIDEOS.filter((v) => v.status !== "done")
  .sort((a, b) => (b.progress || 0) - (a.progress || 0))
  .slice(0, 3);

const STATUS_COLOR_MAP: Record<string, string> = {
  researching: "turquoise",
  scripting: "orange",
  voice: "green",
  visuals: "purple",
  storyboard_review: "turquoise",
  rendering: "red",
  done: "green",
  published: "green",
  uploaded: "gold",
  idea_logged: "turquoise",
};

const ACTIVITY_DOT_COLOR: Record<string, string> = {
  success: "var(--green)",
  warning: "var(--orange)",
  info: "var(--turquoise)",
  error: "var(--red)",
};

export default function DashboardPage() {
  return (
    <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
      {/* Page title */}
      <motion.div variants={item}>
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Production Overview
        </h1>
      </motion.div>

      {/* Stat cards row */}
      <motion.div variants={item} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Videos This Month"
          value={publishedCount}
          color="var(--turquoise)"
          ringValue={(publishedCount / 15) * 100}
        />
        <StatCard
          label="In Production"
          value={inProduction}
          color="var(--green)"
          icon={Film}
        />
        <StatCard
          label="Avg Cost/Video"
          value={`$${avgCost.toFixed(2)}`}
          color="var(--gold)"
          icon={DollarSign}
        />
        <StatCard
          label="Avg CTR"
          value={`${avgCtr.toFixed(2)}%`}
          color="var(--red)"
          trend={avgCtr > 5 ? "up" : "down"}
          icon={AlertTriangle}
        />
      </motion.div>

      {/* Pipeline funnel */}
      <motion.div variants={item}>
        <GlassCard className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
              Pipeline
            </h2>
            <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>...</span>
          </div>
          <div className="flex items-center gap-2 overflow-x-auto pb-2">
            {PIPELINE_FUNNEL.map((stage, i) => (
              <div key={stage.label} className="flex items-center gap-2">
                <div
                  className="flex items-center gap-2 px-4 py-2 rounded-full whitespace-nowrap"
                  style={{
                    background: `${stage.color}18`,
                    border: `1px solid ${stage.color}33`,
                  }}
                >
                  <span className="text-xs font-medium" style={{ color: stage.color }}>
                    {stage.label}
                  </span>
                  <span
                    className="text-[10px] font-mono px-1.5 py-0.5 rounded-full"
                    style={{
                      background: `${stage.color}22`,
                      color: stage.color,
                    }}
                  >
                    {stage.count}
                  </span>
                </div>
                {i < PIPELINE_FUNNEL.length - 1 && (
                  <div className="w-4 h-px" style={{ background: "var(--text-tertiary)", opacity: 0.3 }} />
                )}
              </div>
            ))}
          </div>
        </GlassCard>
      </motion.div>

      {/* Two-column: Activity + Up Next */}
      <motion.div variants={item} className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Activity Feed */}
        <GlassCard className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
              Activity
            </h2>
            <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>...</span>
          </div>
          <div className="space-y-3">
            {MOCK_ACTIVITY.map((a) => (
              <div key={a.id} className="flex items-start gap-3">
                <div
                  className="w-2 h-2 rounded-full mt-1.5 shrink-0"
                  style={{ background: ACTIVITY_DOT_COLOR[a.type] }}
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm" style={{ color: "var(--text-primary)" }}>
                    {a.message}{" "}
                    <span style={{ color: "var(--text-secondary)" }}>
                      — {a.videoTitle}
                    </span>
                  </p>
                  <p className="text-[11px] font-mono mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                    {a.timestamp}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Up Next */}
        <GlassCard className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
              Video
            </h2>
            <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>...</span>
          </div>
          <div className="space-y-4">
            {upNext.map((v) => (
              <div key={v.id} className="flex items-center gap-4">
                {/* Thumbnail placeholder */}
                <div
                  className="w-16 h-10 rounded-lg shrink-0 flex items-center justify-center"
                  style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}
                >
                  <Film size={14} style={{ color: "var(--text-tertiary)" }} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>
                    {v.title}
                  </p>
                  {/* Progress bar */}
                  <div className="mt-1.5 h-1 rounded-full overflow-hidden" style={{ background: "var(--bg-elevated)" }}>
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${v.progress || 0}%`,
                        background: "var(--turquoise)",
                      }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      </motion.div>
    </motion.div>
  );
}
