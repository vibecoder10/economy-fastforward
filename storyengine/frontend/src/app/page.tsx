"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Film,
  Loader2,
  DollarSign,
  TrendingUp,
  Plus,
  ChevronRight,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatCard } from "@/components/ui/StatCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import {
  getDashboardSummary,
  getVideos,
  getActivity,
  getPendingReview,
  type VideoSummary,
  type DashboardSummary,
  type ActivityEntry,
} from "@/lib/api";
import { PIPELINE_STAGES, COMPLETED_STATUSES, getStageLabel } from "@/lib/constants";
import { formatCost, timeAgo } from "@/lib/utils";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

function getStageColor(key: string): string {
  const map: Record<string, string> = {
    idea_logged: "var(--text-secondary)",
    ready_for_scripting: "var(--turquoise)",
    ready_for_voice: "var(--turquoise)",
    ready_for_storyboards: "var(--turquoise)",
    ready_for_images: "var(--turquoise)",
    ready_for_thumbnail: "var(--gold)",
    ready_to_render: "var(--orange)",
    rendered: "var(--green)",
    uploaded_draft: "var(--gold)",
    done: "var(--green)",
  };
  return map[key] || "var(--text-secondary)";
}

function computeProgress(status: string | null): number {
  if (!status) return 0;
  const idx = PIPELINE_STAGES.findIndex((s) => s.key === status);
  if (idx < 0) return 0;
  return Math.round(((idx + 1) / PIPELINE_STAGES.length) * 100);
}

const ACTIVITY_DOT_COLOR: Record<string, string> = {
  completed: "var(--green)",
  running: "var(--turquoise)",
  failed: "var(--red)",
  started: "var(--turquoise)",
  pending: "var(--text-tertiary)",
};

export default function HomePage() {
  const router = useRouter();

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: getDashboardSummary,
  });

  const { data: videos, isLoading: videosLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  const { data: activity } = useQuery({
    queryKey: ["activity"],
    queryFn: () => getActivity(),
  });

  const { data: pendingReview } = useQuery({
    queryKey: ["pending-review"],
    queryFn: getPendingReview,
  });

  const isLoading = summaryLoading || videosLoading;

  // Derived stats
  const stats = useMemo(() => {
    if (!videos) return null;

    const now = new Date();
    const thisMonth = videos.filter((v) => {
      if (!v.created_at) return false;
      const d = new Date(v.created_at);
      return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
    });

    const inProduction = videos.filter(
      (v) => v.status && !COMPLETED_STATUSES.has(v.status)
    );

    const publishedWithCtr = videos.filter((v) => v.ctr !== null && v.ctr !== undefined);
    const avgCtr =
      publishedWithCtr.length > 0
        ? publishedWithCtr.reduce((sum, v) => sum + (v.ctr || 0), 0) / publishedWithCtr.length
        : 0;

    const totalCost = videos.reduce((sum, v) => sum + (v.total_cost || 0), 0);
    const avgCost = videos.length > 0 ? totalCost / videos.length : 0;

    return {
      videosThisMonth: thisMonth.length,
      inProduction: inProduction.length,
      avgCost,
      avgCtr,
    };
  }, [videos]);

  // Pipeline distribution
  const stageDistribution = useMemo(() => {
    if (!summary?.pipeline_distribution) return [];
    return PIPELINE_STAGES.map((stage) => ({
      ...stage,
      count: summary.pipeline_distribution[stage.key] || 0,
    }));
  }, [summary]);

  // Recently active videos
  const recentVideos = useMemo(() => {
    if (!videos) return [];
    return [...videos]
      .sort((a, b) => {
        const aDate = a.updated_at ? new Date(a.updated_at).getTime() : 0;
        const bDate = b.updated_at ? new Date(b.updated_at).getTime() : 0;
        return bDate - aDate;
      })
      .slice(0, 5);
  }, [videos]);

  // Recent activity entries
  const recentActivity = useMemo(() => {
    if (!activity) return [];
    return activity.slice(0, 8);
  }, [activity]);

  // Pending review count
  const pendingCount = useMemo(() => {
    if (!pendingReview) return 0;
    return (
      pendingReview.scripts.length +
      pendingReview.thumbnails.length +
      pendingReview.images.length +
      pendingReview.storyboards.length
    );
  }, [pendingReview]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Production Overview
        </h1>
        <ActionButton icon={Plus} onClick={() => router.push("/pipeline")}>
          Create Video
        </ActionButton>
      </motion.div>

      {/* Stat Cards */}
      <motion.div variants={item} className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Videos This Month"
          value={stats?.videosThisMonth ?? 0}
          color="var(--turquoise)"
          icon={Film}
        />
        <StatCard
          label="In Production"
          value={stats?.inProduction ?? 0}
          color="var(--orange)"
          icon={Loader2}
        />
        <StatCard
          label="Avg Cost / Video"
          value={formatCost(stats?.avgCost ?? 0)}
          color="var(--gold)"
          icon={DollarSign}
        />
        <StatCard
          label="Avg CTR"
          value={stats?.avgCtr ? `${stats.avgCtr.toFixed(1)}%` : "--"}
          color="var(--green)"
          icon={TrendingUp}
        />
      </motion.div>

      {/* Pipeline Stage Tracker */}
      {stageDistribution.length > 0 && (
        <motion.div variants={item}>
          <GlassCard className="!p-4">
            <h2
              className="text-[11px] font-semibold uppercase tracking-wider mb-4"
              style={{ color: "var(--text-secondary)" }}
            >
              Pipeline
            </h2>
            <div className="flex items-end gap-1 h-20">
              {stageDistribution.map((stage) => {
                const maxCount = Math.max(...stageDistribution.map((s) => s.count), 1);
                const height = stage.count > 0 ? Math.max(16, (stage.count / maxCount) * 100) : 4;

                return (
                  <button
                    key={stage.key}
                    onClick={() => router.push(`/pipeline?filter=${stage.key}`)}
                    className="flex-1 flex flex-col items-center gap-1 group cursor-pointer"
                    title={`${stage.label}: ${stage.count} video${stage.count !== 1 ? "s" : ""}`}
                  >
                    {stage.count > 0 && (
                      <span
                        className="text-[10px] font-mono font-bold opacity-0 group-hover:opacity-100 transition-opacity"
                        style={{ color: getStageColor(stage.key) }}
                      >
                        {stage.count}
                      </span>
                    )}
                    <div
                      className="w-full rounded-t transition-all group-hover:brightness-125"
                      style={{
                        height: `${height}%`,
                        minHeight: 4,
                        background: stage.count > 0 ? getStageColor(stage.key) : "rgba(255,255,255,0.05)",
                        opacity: stage.count > 0 ? 1 : 0.3,
                      }}
                    />
                    <span
                      className="text-[9px] font-medium truncate w-full text-center"
                      style={{ color: "var(--text-tertiary)" }}
                    >
                      {stage.label}
                    </span>
                  </button>
                );
              })}
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Two-column: Activity + Recent Videos */}
      <motion.div variants={item} className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Activity Feed */}
        <GlassCard>
          <div className="flex items-center justify-between mb-4">
            <h2
              className="text-[11px] font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-secondary)" }}
            >
              Activity
            </h2>
            {pendingCount > 0 && (
              <StatusPill
                label={`${pendingCount} pending`}
                color="orange"
                size="sm"
              />
            )}
          </div>

          {recentActivity.length === 0 ? (
            <div
              className="rounded-xl p-8 text-center"
              style={{ background: "rgba(255,255,255,0.02)" }}
            >
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                No activity yet. Create your first video to get started.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {recentActivity.map((a) => (
                <div
                  key={a.id}
                  className="flex items-start gap-3 cursor-pointer rounded-lg p-2 transition-colors"
                  style={{ background: "transparent" }}
                  onClick={() => a.video_id && router.push(`/pipeline/${a.video_id}`)}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "rgba(255,255,255,0.03)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "transparent";
                  }}
                >
                  <div
                    className="w-2 h-2 rounded-full mt-1.5 shrink-0"
                    style={{ background: ACTIVITY_DOT_COLOR[a.status] || "var(--text-tertiary)" }}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm" style={{ color: "var(--text-primary)" }}>
                      {a.message || a.bot_name}{" "}
                      {a.video_title && (
                        <span style={{ color: "var(--text-secondary)" }}>
                          — {a.video_title}
                        </span>
                      )}
                    </p>
                    <p className="text-[11px] font-mono mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                      {timeAgo(a.created_at)}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>

        {/* Recent Videos */}
        <GlassCard>
          <div className="flex items-center justify-between mb-4">
            <h2
              className="text-[11px] font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-secondary)" }}
            >
              Recent Videos
            </h2>
            <button
              onClick={() => router.push("/pipeline")}
              className="text-xs font-medium transition-colors hover:brightness-125"
              style={{ color: "var(--turquoise)" }}
            >
              View All
              <ChevronRight size={12} className="inline ml-0.5" />
            </button>
          </div>

          {recentVideos.length === 0 ? (
            <div
              className="rounded-xl p-8 text-center"
              style={{ background: "rgba(255,255,255,0.02)" }}
            >
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                No videos yet. Create your first video to get started.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {recentVideos.map((v) => {
                const progress = computeProgress(v.status);
                return (
                  <button
                    key={v.id}
                    onClick={() => router.push(`/pipeline/${v.id}`)}
                    className="w-full flex items-center gap-3 p-3 rounded-xl text-left transition-all duration-200"
                    style={{
                      background: "rgba(255,255,255,0.02)",
                      border: "1px solid rgba(255,255,255,0.04)",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = "rgba(255,255,255,0.05)";
                      e.currentTarget.style.borderColor = "rgba(0, 212, 170, 0.15)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "rgba(255,255,255,0.02)";
                      e.currentTarget.style.borderColor = "rgba(255,255,255,0.04)";
                    }}
                  >
                    <div className="flex-1 min-w-0">
                      <p
                        className="text-sm font-medium truncate"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {v.video_title || "Untitled"}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <StatusPill
                          label={getStageLabel(v.status || "")}
                          color={
                            COMPLETED_STATUSES.has(v.status || "")
                              ? "green"
                              : "turquoise"
                          }
                          size="sm"
                        />
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          {timeAgo(v.updated_at)}
                        </span>
                      </div>
                    </div>
                    {/* Progress bar */}
                    <div className="w-20 shrink-0">
                      <div className="flex items-center justify-end gap-1.5 mb-1">
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          {progress}%
                        </span>
                      </div>
                      <div
                        className="h-1 rounded-full overflow-hidden"
                        style={{ background: "rgba(255,255,255,0.06)" }}
                      >
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${progress}%`,
                            background:
                              progress === 100 ? "var(--green)" : "var(--turquoise)",
                          }}
                        />
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </GlassCard>
      </motion.div>
    </motion.div>
  );
}
