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
  AlertCircle,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatCard } from "@/components/ui/StatCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import {
  getDashboardSummary,
  getVideos,
  getPendingReview,
  type VideoSummary,
  type PendingReview,
  type DashboardSummary,
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

export default function DashboardPage() {
  const router = useRouter();

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: getDashboardSummary,
  });

  const { data: videos, isLoading: videosLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  const { data: pendingReview } = useQuery({
    queryKey: ["pending-review"],
    queryFn: getPendingReview,
  });

  const isLoading = summaryLoading || videosLoading;

  // Derived stats
  const stats = useMemo(() => {
    if (!videos || !summary) return null;

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
  }, [videos, summary]);

  // Pipeline distribution
  const stageDistribution = useMemo(() => {
    if (!summary?.pipeline_distribution) return [];
    return PIPELINE_STAGES.map((stage) => ({
      ...stage,
      count: summary.pipeline_distribution[stage.key] || 0,
    }));
  }, [summary]);

  // Recently active videos (sorted by updated_at)
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

  // Actionable items from pending review
  const actionItems = useMemo(() => {
    if (!pendingReview) return [];
    const items: { type: string; title: string; videoId: string; count?: number; color: string }[] = [];

    if (pendingReview.scripts.length > 0) {
      pendingReview.scripts.forEach((s) => {
        items.push({
          type: "Script Review",
          title: s.title || "Untitled",
          videoId: s.video_id,
          color: "var(--orange)",
        });
      });
    }
    if (pendingReview.thumbnails.length > 0) {
      pendingReview.thumbnails.forEach((t) => {
        items.push({
          type: "Thumbnail Review",
          title: t.title || "Untitled",
          videoId: t.video_id,
          color: "var(--gold)",
        });
      });
    }
    if (pendingReview.images.length > 0) {
      // Group images by video
      const byVideo = new Map<string, { title: string; count: number }>();
      pendingReview.images.forEach((img) => {
        const existing = byVideo.get(img.video_id);
        if (existing) {
          existing.count++;
        } else {
          byVideo.set(img.video_id, { title: img.title || "Untitled", count: 1 });
        }
      });
      byVideo.forEach((val, videoId) => {
        items.push({
          type: `${val.count} Image${val.count > 1 ? "s" : ""} Pending`,
          title: val.title,
          videoId,
          color: "var(--turquoise)",
        });
      });
    }
    if (pendingReview.storyboards.length > 0) {
      pendingReview.storyboards.forEach((sb) => {
        items.push({
          type: "Storyboard Review",
          title: sb.title || "Untitled",
          videoId: sb.video_id,
          color: "var(--green)",
        });
      });
    }

    return items.slice(0, 6);
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
          Dashboard
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
      <motion.div variants={item}>
        <GlassCard className="!p-4">
          <h2
            className="text-[11px] font-semibold uppercase tracking-wider mb-4"
            style={{ color: "var(--text-secondary)" }}
          >
            Pipeline Distribution
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

      {/* Two-column: Activity Feed + Recent Videos */}
      <motion.div variants={item} className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Approval Queue */}
        <GlassCard>
          <div className="flex items-center justify-between mb-4">
            <h2
              className="text-[11px] font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-secondary)" }}
            >
              Needs Attention
            </h2>
            {actionItems.length > 0 && (
              <StatusPill
                label={`${actionItems.length} item${actionItems.length !== 1 ? "s" : ""}`}
                color="orange"
                size="sm"
              />
            )}
          </div>

          {actionItems.length === 0 ? (
            <div
              className="rounded-xl p-8 text-center"
              style={{ background: "rgba(255,255,255,0.02)" }}
            >
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                All clear. Nothing needs review right now.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {actionItems.map((a, i) => (
                <button
                  key={`${a.videoId}-${a.type}-${i}`}
                  onClick={() => router.push(`/pipeline/${a.videoId}`)}
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
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ background: a.color, boxShadow: `0 0 6px ${a.color}` }}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>
                      {a.title}
                    </p>
                    <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                      {a.type}
                    </p>
                  </div>
                  <ChevronRight size={14} style={{ color: "var(--text-tertiary)" }} />
                </button>
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
