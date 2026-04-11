"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  Cell,
} from "recharts";
import { ArrowUpDown, RefreshCw, Loader2, Brain, TrendingUp, TrendingDown, Zap, Eye, BarChart3, Target, Film } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatCard } from "@/components/ui/StatCard";
import { VerdictBadge } from "@/components/ui/VerdictBadge";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorCard } from "@/components/ui/ErrorCard";
import {
  getVideos,
  getLearnings,
  syncYouTubeMetrics,
  getYouTubeSyncStatus,
  getAnalyticsOverview,
  getCTRTimeline,
  getFrameworkPerformance,
  getTopicPerformance,
  getCompetitorBenchmark,
  getIntelligenceStats,
  getTopicInsights,
  getHookInsights,
  getThumbnailInsights,
  getTimingInsights,
  getIntelligenceRecommendations,
  getNicheMetaInsights,
  triggerMetaAnalysis,
  type VideoSummary,
  type LearningRecord,
  type AnalyticsOverview,
  type CTRTimelinePoint,
  type FrameworkPerformance,
  type TopicPerformance,
  type CompetitorBenchmark,
  type IntelligenceStats,
  type TopicInsight,
  type HookInsight,
  type ThumbnailInsights,
  type TimingInsights,
  type IntelligenceRecommendations,
} from "@/lib/api";
import { COMPLETED_STATUSES } from "@/lib/constants";
import { formatNumber, timeAgo } from "@/lib/utils";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: "easeOut" as const } },
};

type SortKey = "views" | "ctr" | "created_at";
type SortDir = "asc" | "desc";

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "--";
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function getVerdict(ctr: number | null | undefined): "hit" | "steady" | "underperformed" | null {
  if (ctr === null || ctr === undefined) return null;
  if (ctr >= 5) return "hit";
  if (ctr >= 3) return "steady";
  return "underperformed";
}

function ctrColor(ctr: number | null | undefined): string {
  if (ctr === null || ctr === undefined) return "var(--text-tertiary)";
  if (ctr >= 5) return "var(--green)";
  if (ctr >= 3) return "var(--gold)";
  return "var(--red)";
}

function CustomTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ dataKey: string; value: number; color: string; name: string }>; label?: string }) {
  if (!active || !payload) return null;
  return (
    <div
      className="glass-card px-4 py-3 text-xs"
      style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
    >
      <p className="font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
        {label}
      </p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {p.dataKey === "views" ? formatNumber(p.value) : `${p.value.toFixed(1)}%`}
        </p>
      ))}
    </div>
  );
}

const FRAMEWORK_COLORS = [
  "var(--turquoise)",
  "var(--gold)",
  "var(--purple)",
  "var(--orange)",
  "var(--green)",
  "var(--red)",
  "var(--yellow)",
];

export default function AnalyticsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Analytics endpoints
  const { data: overview, isLoading: overviewLoading, error: overviewError } = useQuery({
    queryKey: ["analytics-overview"],
    queryFn: getAnalyticsOverview,
  });

  const { data: ctrTimeline, isLoading: timelineLoading } = useQuery({
    queryKey: ["analytics-ctr-timeline"],
    queryFn: () => getCTRTimeline(50),
  });

  const { data: frameworks } = useQuery({
    queryKey: ["analytics-framework-performance"],
    queryFn: getFrameworkPerformance,
  });

  const { data: topics } = useQuery({
    queryKey: ["analytics-topic-performance"],
    queryFn: getTopicPerformance,
  });

  const { data: benchmark } = useQuery({
    queryKey: ["analytics-competitor-benchmark"],
    queryFn: getCompetitorBenchmark,
  });

  // Video list for table
  const { data: allVideos, isLoading: videosLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  // Learning system data
  const { data: learnings } = useQuery({
    queryKey: ["learnings"],
    queryFn: () => getLearnings(undefined, false),
  });

  // Niche Intelligence (from content_intelligence distillation)
  const { data: intelStats } = useQuery({
    queryKey: ["intelligence-stats"],
    queryFn: getIntelligenceStats,
  });
  const { data: nicheTopics } = useQuery({
    queryKey: ["intelligence-topics"],
    queryFn: () => getTopicInsights(10),
  });
  const { data: nicheHooks } = useQuery({
    queryKey: ["intelligence-hooks"],
    queryFn: getHookInsights,
  });
  const { data: nicheThumbnails } = useQuery({
    queryKey: ["intelligence-thumbnails"],
    queryFn: getThumbnailInsights,
  });
  const { data: nicheTiming } = useQuery({
    queryKey: ["intelligence-timing"],
    queryFn: getTimingInsights,
  });
  const { data: nicheRecs } = useQuery({
    queryKey: ["intelligence-recommendations"],
    queryFn: getIntelligenceRecommendations,
  });
  const { data: metaInsights } = useQuery({
    queryKey: ["intelligence-meta-insights"],
    queryFn: getNicheMetaInsights,
  });
  const metaAnalysisMutation = useMutation({
    mutationFn: triggerMetaAnalysis,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["intelligence-meta-insights"] }),
  });

  // YouTube sync status
  const { data: syncStatus } = useQuery({
    queryKey: ["youtube-sync-status"],
    queryFn: getYouTubeSyncStatus,
    refetchInterval: (query) => {
      if (query.state.data?.is_running) return 3000;
      return false;
    },
  });

  const syncMutation = useMutation({
    mutationFn: syncYouTubeMetrics,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["youtube-sync-status"] });
    },
  });

  const syncRunning = syncStatus?.is_running ?? false;
  const prevRunning = useRef(false);

  useEffect(() => {
    if (prevRunning.current && !syncRunning) {
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      queryClient.invalidateQueries({ queryKey: ["analytics-overview"] });
      queryClient.invalidateQueries({ queryKey: ["analytics-ctr-timeline"] });
      queryClient.invalidateQueries({ queryKey: ["analytics-framework-performance"] });
      queryClient.invalidateQueries({ queryKey: ["analytics-topic-performance"] });
      queryClient.invalidateQueries({ queryKey: ["analytics-competitor-benchmark"] });
    }
    prevRunning.current = syncRunning;
  }, [syncRunning, queryClient]);

  // Filter to published/uploaded videos for table
  const publishedVideos = useMemo(() => {
    if (!allVideos) return [];
    return allVideos.filter(
      (v) => COMPLETED_STATUSES.has(v.status || "") || v.views > 0 || v.ctr !== null
    );
  }, [allVideos]);

  // Chart data from CTR timeline endpoint
  const chartData = useMemo(() => {
    if (!ctrTimeline) return [];
    return ctrTimeline.map((p) => ({
      date: formatDate(p.date),
      views: p.views || 0,
      ctr: p.ctr ?? 0,
      title: p.video_title || "Untitled",
    }));
  }, [ctrTimeline]);

  // Framework chart data
  const frameworkChartData = useMemo(() => {
    if (!frameworks) return [];
    return frameworks.map((f) => ({
      name: f.framework.length > 20 ? f.framework.slice(0, 20) + "…" : f.framework,
      fullName: f.framework,
      avg_ctr: f.avg_ctr ?? 0,
      video_count: f.video_count,
      total_views: f.total_views,
    }));
  }, [frameworks]);

  // Sorted table data
  const sortedVideos = useMemo(() => {
    return [...publishedVideos].sort((a, b) => {
      let aVal: number;
      let bVal: number;
      switch (sortKey) {
        case "views":
          aVal = a.views || 0;
          bVal = b.views || 0;
          break;
        case "ctr":
          aVal = a.ctr ?? -1;
          bVal = b.ctr ?? -1;
          break;
        case "created_at":
        default:
          aVal = a.created_at ? new Date(a.created_at).getTime() : 0;
          bVal = b.created_at ? new Date(b.created_at).getTime() : 0;
          break;
      }
      return sortDir === "desc" ? bVal - aVal : aVal - bVal;
    });
  }, [publishedVideos, sortKey, sortDir]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const isLoading = overviewLoading && videosLoading;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    );
  }

  if (overviewError && !overview) {
    return (
      <ErrorCard
        title="Analytics unavailable"
        message="Unable to load analytics data. The server may need to be restarted."
        onRetry={() => window.location.reload()}
      />
    );
  }

  const sortableHeader = (label: string, key: SortKey) => (
    <button
      onClick={() => handleSort(key)}
      className="inline-flex items-center gap-1 hover:brightness-125 transition-colors"
    >
      {label}
      <ArrowUpDown
        size={10}
        style={{ color: sortKey === key ? "var(--turquoise)" : "var(--text-tertiary)" }}
      />
    </button>
  );

  return (
    <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between gap-4 flex-wrap">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Analytics
        </h1>
        <div className="flex items-center gap-3">
          <ActionButton
            icon={syncRunning ? undefined : RefreshCw}
            onClick={() => syncMutation.mutate()}
            disabled={syncRunning || syncMutation.isPending}
          >
            {syncRunning ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                <span className="ml-1">
                  Syncing {syncStatus?.videos_synced ?? 0}/{syncStatus?.videos_total ?? 0}...
                </span>
              </>
            ) : (
              "Sync YouTube"
            )}
          </ActionButton>
          {syncStatus?.last_run && !syncRunning && (
            <span className="text-[11px] font-mono" style={{ color: "var(--text-tertiary)" }}>
              Last sync: {timeAgo(syncStatus.last_run)}
            </span>
          )}
        </div>
      </motion.div>

      {/* Sync error display */}
      {syncStatus && !syncRunning && (syncStatus.error || (syncStatus.errors?.length ?? 0) > 0) && (
        <motion.div variants={item}>
          <div
            className="rounded-xl px-4 py-3 flex flex-col gap-2"
            style={{ background: "rgba(196,69,69,0.1)", border: "1px solid rgba(196,69,69,0.3)" }}
          >
            {syncStatus.error && (
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm" style={{ color: "#C44545" }}>
                  Sync error{syncStatus.error_type ? ` (${syncStatus.error_type})` : ""}: {syncStatus.error}
                </span>
                {syncStatus.error_type === "auth" && (
                  <a
                    href="/settings/keys"
                    className="text-xs px-3 py-1 rounded-lg font-medium whitespace-nowrap"
                    style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
                  >
                    Re-connect YouTube
                  </a>
                )}
              </div>
            )}
            {(syncStatus.videos_failed ?? 0) > 0 && (
              <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                {syncStatus.videos_failed} of {syncStatus.videos_total} videos failed to sync
                {(syncStatus.videos_retried ?? 0) > 0 && ` (${syncStatus.videos_retried} retried)`}
              </span>
            )}
            {syncStatus.errors?.slice(0, 5).map((e, i) => (
              <span key={i} className="text-[11px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                {e.error_type}: {e.message}
              </span>
            ))}
          </div>
        </motion.div>
      )}

      {/* Overview Stats */}
      {overview && (
        <motion.div variants={item} className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard
            label="Total Videos"
            value={overview.total_videos.toString()}
            detail={`${overview.published_videos} published`}
            color="var(--turquoise)"
            icon={Film}
          />
          <StatCard
            label="Total Views"
            value={formatNumber(overview.total_views)}
            color="var(--purple)"
            icon={Eye}
          />
          <StatCard
            label="Avg CTR"
            value={overview.avg_ctr !== null ? `${overview.avg_ctr.toFixed(1)}%` : "--"}
            color={ctrColor(overview.avg_ctr)}
            icon={Target}
          />
          <StatCard
            label="Avg Retention"
            value={overview.avg_retention !== null ? `${overview.avg_retention.toFixed(1)}%` : "--"}
            color="var(--gold)"
            icon={BarChart3}
          />
        </motion.div>
      )}

      {/* CTR Timeline Chart */}
      <motion.div variants={item}>
        <GlassCard className="p-6">
          <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            Views &amp; CTR Over Time
          </h2>
          {timelineLoading ? (
            <div className="h-72 flex items-center justify-center">
              <Spinner />
            </div>
          ) : chartData.length === 0 ? (
            <EmptyState
              icon={TrendingUp}
              title="No performance data yet"
              description="Publish videos to see CTR and views charts here."
            />
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="date"
                    tick={{ fill: "var(--text-tertiary)", fontSize: 11 }}
                    axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
                  />
                  <YAxis
                    yAxisId="views"
                    tick={{ fill: "var(--text-tertiary)", fontSize: 11 }}
                    axisLine={false}
                    tickFormatter={(v: number) => formatNumber(v)}
                  />
                  <YAxis
                    yAxisId="ctr"
                    orientation="right"
                    tick={{ fill: "var(--text-tertiary)", fontSize: 11 }}
                    axisLine={false}
                    tickFormatter={(v: number) => `${v}%`}
                    domain={[0, "auto"]}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11, color: "var(--text-secondary)" }} />
                  <Line
                    yAxisId="views"
                    type="monotone"
                    dataKey="views"
                    name="Views"
                    stroke="var(--turquoise)"
                    strokeWidth={2}
                    dot={{ r: 4, fill: "var(--turquoise)" }}
                    activeDot={{ r: 6 }}
                  />
                  <Line
                    yAxisId="ctr"
                    type="monotone"
                    dataKey="ctr"
                    name="CTR %"
                    stroke="var(--gold)"
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    dot={{ r: 4, fill: "var(--gold)" }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </GlassCard>
      </motion.div>

      {/* Framework Performance */}
      {frameworks && frameworks.length > 0 && (
        <motion.div variants={item}>
          <GlassCard className="p-6">
            <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
              Framework Effectiveness
            </h2>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Bar chart */}
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={frameworkChartData} layout="vertical">
                    <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                    <XAxis
                      type="number"
                      tick={{ fill: "var(--text-tertiary)", fontSize: 11 }}
                      axisLine={false}
                      tickFormatter={(v: number) => `${v}%`}
                    />
                    <YAxis
                      dataKey="name"
                      type="category"
                      tick={{ fill: "var(--text-secondary)", fontSize: 11 }}
                      axisLine={false}
                      width={120}
                    />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.[0]) return null;
                        const d = payload[0].payload;
                        return (
                          <div
                            className="glass-card px-4 py-3 text-xs"
                            style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
                          >
                            <p className="font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
                              {d.fullName}
                            </p>
                            <p style={{ color: "var(--turquoise)" }}>Avg CTR: {d.avg_ctr.toFixed(1)}%</p>
                            <p style={{ color: "var(--text-secondary)" }}>{d.video_count} videos · {formatNumber(d.total_views)} views</p>
                          </div>
                        );
                      }}
                    />
                    <Bar dataKey="avg_ctr" radius={[0, 4, 4, 0]}>
                      {frameworkChartData.map((_, i) => (
                        <Cell key={i} fill={FRAMEWORK_COLORS[i % FRAMEWORK_COLORS.length]} fillOpacity={0.8} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Framework table */}
              <div className="space-y-2">
                {frameworks.map((f, i) => (
                  <div
                    key={f.framework}
                    className="flex items-center justify-between p-3 rounded-lg"
                    style={{ background: "rgba(255,255,255,0.03)" }}
                  >
                    <div className="flex items-center gap-3">
                      <div
                        className="w-2 h-2 rounded-full"
                        style={{ background: FRAMEWORK_COLORS[i % FRAMEWORK_COLORS.length] }}
                      />
                      <span className="text-sm" style={{ color: "var(--text-primary)" }}>
                        {f.framework}
                      </span>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                        {f.video_count} videos
                      </span>
                      <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                        {formatNumber(f.total_views)} views
                      </span>
                      <span className="text-sm font-mono font-semibold" style={{ color: ctrColor(f.avg_ctr) }}>
                        {f.avg_ctr !== null ? `${f.avg_ctr.toFixed(1)}%` : "--"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Topic Performance + Competitor Benchmark */}
      {(topics?.length || benchmark) && (
        <motion.div variants={item} className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Topic Performance Chart */}
          {topics && topics.length > 0 && (
            <GlassCard className="p-6">
              <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
                Topic Performance
              </h2>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={topics.slice(0, 8)} layout="vertical">
                    <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                    <XAxis
                      type="number"
                      tick={{ fill: "var(--text-tertiary)", fontSize: 11 }}
                      axisLine={false}
                      tickFormatter={(v: number) => formatNumber(v)}
                    />
                    <YAxis
                      dataKey="topic"
                      type="category"
                      tick={{ fill: "var(--text-secondary)", fontSize: 10 }}
                      axisLine={false}
                      width={100}
                      tickFormatter={(v: string) => v.length > 18 ? v.slice(0, 18) + "…" : v}
                    />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.[0]) return null;
                        const d = payload[0].payload as TopicPerformance;
                        return (
                          <div className="glass-card px-4 py-3 text-xs" style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}>
                            <p className="font-semibold mb-1" style={{ color: "var(--text-primary)" }}>{d.topic}</p>
                            <p style={{ color: "var(--turquoise)" }}>{formatNumber(d.total_views)} views</p>
                            <p style={{ color: "var(--text-secondary)" }}>{d.video_count} videos · CTR: {d.avg_ctr !== null ? `${d.avg_ctr.toFixed(1)}%` : "--"}</p>
                          </div>
                        );
                      }}
                    />
                    <Bar dataKey="total_views" radius={[0, 4, 4, 0]}>
                      {topics.slice(0, 8).map((_, i) => (
                        <Cell key={i} fill={FRAMEWORK_COLORS[i % FRAMEWORK_COLORS.length]} fillOpacity={0.8} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>
          )}

          {/* Competitor Benchmark Card */}
          {benchmark && (
            <GlassCard className="p-6">
              <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
                Competitor Benchmark
              </h2>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg p-3" style={{ background: "rgba(255,255,255,0.03)" }}>
                    <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Our Avg CTR</span>
                    <p className="text-lg font-mono font-bold mt-1" style={{ color: ctrColor(benchmark.channel_avg_ctr) }}>
                      {benchmark.channel_avg_ctr !== null ? `${benchmark.channel_avg_ctr.toFixed(1)}%` : "--"}
                    </p>
                  </div>
                  <div className="rounded-lg p-3" style={{ background: "rgba(255,255,255,0.03)" }}>
                    <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Our Total Views</span>
                    <p className="text-lg font-mono font-bold mt-1" style={{ color: "var(--turquoise)" }}>
                      {formatNumber(benchmark.channel_total_views)}
                    </p>
                  </div>
                </div>
                <div>
                  <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                    Competitors by VPH
                  </span>
                  <div className="mt-2 space-y-1.5">
                    {benchmark.competitors.slice(0, 6).map((c) => (
                      <div key={c.channel} className="flex items-center justify-between py-1.5 px-2 rounded-lg" style={{ background: "rgba(255,255,255,0.02)" }}>
                        <span className="text-xs truncate max-w-[160px]" style={{ color: "var(--text-primary)" }}>{c.channel}</span>
                        <div className="flex items-center gap-3">
                          <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                            {c.video_count} vids
                          </span>
                          <span className="text-xs font-mono font-semibold" style={{ color: "var(--gold)" }}>
                            {c.avg_vph !== null ? `${formatNumber(c.avg_vph)} VPH` : "--"}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </GlassCard>
          )}
        </motion.div>
      )}

      {/* System Intelligence */}
      {learnings && learnings.length > 0 && (
        <motion.div variants={item}>
          <GlassCard className="p-6">
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2">
                <Brain size={18} style={{ color: "var(--turquoise)" }} />
                <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  System Intelligence
                </h2>
              </div>
              <span
                className="text-[11px] font-mono px-2 py-1 rounded-full"
                style={{
                  color: "var(--turquoise)",
                  background: "rgba(0, 245, 212, 0.08)",
                  border: "1px solid rgba(0, 245, 212, 0.15)",
                }}
              >
                {learnings.length} patterns learned
              </span>
            </div>

            {(() => {
              const proven = learnings.filter((l) => l.confidence >= 60 && l.active);
              const avoid = learnings.filter((l) => l.confidence <= 30 && l.active);

              return (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Proven */}
                  <div
                    className="rounded-xl p-4"
                    style={{ background: "rgba(0, 200, 83, 0.04)", border: "1px solid rgba(0, 200, 83, 0.1)" }}
                  >
                    <div className="flex items-center gap-2 mb-3">
                      <TrendingUp size={14} style={{ color: "var(--green)" }} />
                      <span className="text-xs font-semibold" style={{ color: "var(--green)" }}>
                        Proven Patterns ({proven.length})
                      </span>
                    </div>
                    {proven.length === 0 ? (
                      <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                        No high-confidence patterns yet. More data needed.
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {proven.slice(0, 6).map((l) => (
                          <div key={l.id} className="flex items-start justify-between gap-2">
                            <span className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                              {l.pattern.length > 80 ? l.pattern.slice(0, 80) + "…" : l.pattern}
                            </span>
                            <div className="flex items-center gap-2 shrink-0">
                              {l.avg_ctr !== null && (
                                <span className="text-[10px] font-mono" style={{ color: "var(--green)" }}>
                                  {l.avg_ctr.toFixed(1)}% CTR
                                </span>
                              )}
                              <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                                n={l.sample_size}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Avoid */}
                  <div
                    className="rounded-xl p-4"
                    style={{ background: "rgba(255, 82, 82, 0.04)", border: "1px solid rgba(255, 82, 82, 0.1)" }}
                  >
                    <div className="flex items-center gap-2 mb-3">
                      <TrendingDown size={14} style={{ color: "var(--red)" }} />
                      <span className="text-xs font-semibold" style={{ color: "var(--red)" }}>
                        Patterns to Avoid ({avoid.length})
                      </span>
                    </div>
                    {avoid.length === 0 ? (
                      <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                        No anti-patterns detected yet.
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {avoid.slice(0, 6).map((l) => (
                          <div key={l.id} className="flex items-start justify-between gap-2">
                            <span className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                              {l.pattern.length > 80 ? l.pattern.slice(0, 80) + "…" : l.pattern}
                            </span>
                            <div className="flex items-center gap-2 shrink-0">
                              {l.avg_ctr !== null && (
                                <span className="text-[10px] font-mono" style={{ color: "var(--red)" }}>
                                  {l.avg_ctr.toFixed(1)}% CTR
                                </span>
                              )}
                              <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                                n={l.sample_size}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              );
            })()}
          </GlassCard>
        </motion.div>
      )}

      {/* Data table */}
      <motion.div variants={item}>
        <GlassCard className="p-6 overflow-x-auto">
          <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            Video Performance
          </h2>
          {sortedVideos.length === 0 ? (
            <EmptyState
              icon={BarChart3}
              title="No published videos to analyze"
              description="Performance data appears after you upload videos to YouTube."
            />
          ) : (
            <table className="w-full text-left">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {[
                    { label: "#", key: null },
                    { label: "Title", key: null },
                    { label: "Upload Date", key: "created_at" as SortKey },
                    { label: "Views", key: "views" as SortKey },
                    { label: "CTR%", key: "ctr" as SortKey },
                    { label: "Verdict", key: null },
                  ].map((h, i) => (
                    <th
                      key={i}
                      className="pb-3 text-[11px] font-semibold uppercase tracking-wider whitespace-nowrap px-3"
                      style={{ color: "var(--text-tertiary)" }}
                    >
                      {h.key ? sortableHeader(h.label, h.key) : h.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedVideos.map((v, i) => {
                  const verdict = getVerdict(v.ctr);
                  return (
                    <tr
                      key={v.id}
                      className="transition-colors hover:bg-[rgba(255,255,255,0.03)] cursor-pointer group"
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}
                      onClick={() => router.push(`/pipeline/${v.id}`)}
                    >
                      <td className="py-3 px-3">
                        <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                          {i + 1}
                        </span>
                      </td>
                      <td className="py-3 px-3 max-w-[300px]">
                        <span
                          className="text-sm font-medium truncate block group-hover:text-[var(--turquoise)] transition-colors"
                          style={{ color: "var(--text-primary)" }}
                        >
                          {v.video_title || "Untitled"}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                          {formatDate(v.created_at)}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>
                          {formatNumber(v.views || 0)}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="text-sm font-mono" style={{ color: ctrColor(v.ctr) }}>
                          {v.ctr !== null && v.ctr !== undefined ? `${v.ctr.toFixed(1)}%` : "--"}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        {verdict && <VerdictBadge verdict={verdict} />}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </GlassCard>
      {/* ── Niche Intelligence (from distilled competitor DNA) ── */}
      {intelStats && intelStats.distilled > 0 && (
        <motion.div variants={item} className="space-y-4">
          <div className="flex items-center gap-2">
            <Brain size={16} style={{ color: "var(--amber)" }} />
            <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
              Niche Intelligence
            </h2>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full" style={{ background: "rgba(251,191,36,0.12)", color: "var(--amber)" }}>
              {intelStats.distilled} videos analyzed
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Hook Patterns */}
            {nicheHooks?.hooks && nicheHooks.hooks.length > 0 && (
              <GlassCard>
                <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--amber)" }}>
                  Hook Patterns
                </h3>
                <div className="space-y-2">
                  {nicheHooks.hooks.slice(0, 5).map((h) => (
                    <div key={h.hook_type} className="flex items-center justify-between">
                      <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{h.hook_type}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>{h.count}x</span>
                        <span className="text-[10px] font-mono font-bold" style={{ color: "var(--turquoise)" }}>
                          {formatNumber(h.avg_vph)} VPH
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </GlassCard>
            )}

            {/* Thumbnail Styles */}
            {nicheThumbnails?.styles && nicheThumbnails.styles.length > 0 && (
              <GlassCard>
                <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--amber)" }}>
                  Thumbnail Styles
                </h3>
                <div className="space-y-2">
                  {nicheThumbnails.styles.slice(0, 5).map((s) => (
                    <div key={s.style} className="flex items-center justify-between">
                      <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{s.style}</span>
                      <span className="text-[10px] font-mono font-bold" style={{ color: "var(--turquoise)" }}>
                        {formatNumber(s.avg_vph)} VPH
                      </span>
                    </div>
                  ))}
                  {nicheThumbnails.face_present && nicheThumbnails.face_present.length > 0 && (
                    <div className="pt-2 mt-2" style={{ borderTop: "1px solid var(--border)" }}>
                      {nicheThumbnails.face_present.map((f) => (
                        <div key={String(f.face_present)} className="flex items-center justify-between">
                          <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                            {f.face_present ? "Face shown" : "No face"}
                          </span>
                          <span className="text-[10px] font-mono" style={{ color: "var(--turquoise)" }}>
                            {formatNumber(f.avg_vph)} VPH ({f.count})
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </GlassCard>
            )}

            {/* Best Publish Times */}
            {nicheTiming?.by_day && nicheTiming.by_day.length > 0 && (
              <GlassCard>
                <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--amber)" }}>
                  Best Publish Days
                </h3>
                <div className="space-y-1.5">
                  {nicheTiming.by_day
                    .sort((a, b) => b.avg_vph - a.avg_vph)
                    .slice(0, 7)
                    .map((d) => (
                      <div key={d.day_name} className="flex items-center gap-2">
                        <span className="text-xs w-16 shrink-0" style={{ color: "var(--text-secondary)" }}>
                          {d.day_name.slice(0, 3)}
                        </span>
                        <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${Math.min(100, (d.avg_vph / Math.max(...nicheTiming.by_day.map(x => x.avg_vph))) * 100)}%`,
                              background: "var(--turquoise)",
                            }}
                          />
                        </div>
                        <span className="text-[10px] font-mono w-12 text-right" style={{ color: "var(--turquoise)" }}>
                          {formatNumber(d.avg_vph)}
                        </span>
                      </div>
                    ))}
                </div>
                {nicheTiming.by_hour && nicheTiming.by_hour.length > 0 && (() => {
                  const bestHour = nicheTiming.by_hour.sort((a, b) => b.avg_vph - a.avg_vph)[0];
                  return (
                    <p className="text-[10px] mt-3 pt-2" style={{ borderTop: "1px solid var(--border)", color: "var(--text-muted)" }}>
                      Best hour: <span style={{ color: "var(--amber)" }}>{bestHour.hour}:00</span> ({formatNumber(bestHour.avg_vph)} avg VPH)
                    </p>
                  );
                })()}
              </GlassCard>
            )}

            {/* Top Topics */}
            {nicheTopics?.topics && nicheTopics.topics.length > 0 && (
              <GlassCard>
                <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--amber)" }}>
                  Trending Topics
                </h3>
                <div className="space-y-2">
                  {nicheTopics.topics.slice(0, 8).map((t) => (
                    <div key={t.topic} className="flex items-center justify-between">
                      <span className="text-xs truncate mr-2" style={{ color: "var(--text-secondary)" }}>{t.topic}</span>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>{t.count}x</span>
                        <span className="text-[10px] font-mono font-bold" style={{ color: "var(--turquoise)" }}>
                          {formatNumber(t.avg_vph)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </GlassCard>
            )}
          </div>

          {/* Compression stats */}
          <div className="flex items-center gap-4 text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>
            <span>{intelStats.pending} pending distillation</span>
            <span>{intelStats.compression_ratio}x compression</span>
            <span>{intelStats.estimated_savings_mb.toFixed(1)} MB saved</span>
          </div>

          {/* Intelligence Recommendations */}
          {nicheRecs?.status === "ok" && nicheRecs.recommendations && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Target size={14} style={{ color: "var(--emerald)" }} />
                <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  AI Recommendations
                </h3>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full" style={{ background: "rgba(52,211,153,0.12)", color: "var(--emerald)" }}>
                  {Math.round(nicheRecs.recommendations.confidence * 100)}% confidence
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                {/* Best Hook */}
                {nicheRecs.recommendations.hook && (
                  <GlassCard className="p-3 space-y-1">
                    <div className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Best Hook</div>
                    <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                      {nicheRecs.recommendations.hook.type.replace(/_/g, " ")}
                    </div>
                    <div className="text-[11px]" style={{ color: "var(--amber)" }}>
                      {nicheRecs.recommendations.hook.avg_vph.toLocaleString()} avg VPH · {nicheRecs.recommendations.hook.count} videos
                    </div>
                  </GlassCard>
                )}
                {/* Best Title Structure */}
                {nicheRecs.recommendations.title_structure && (
                  <GlassCard className="p-3 space-y-1">
                    <div className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Best Title Structure</div>
                    <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                      {nicheRecs.recommendations.title_structure.structure.replace(/_/g, " ")}
                    </div>
                    <div className="text-[11px]" style={{ color: "var(--amber)" }}>
                      {nicheRecs.recommendations.title_structure.avg_vph.toLocaleString()} avg VPH
                    </div>
                  </GlassCard>
                )}
                {/* Best Thumbnail */}
                {nicheRecs.recommendations.thumbnail && (
                  <GlassCard className="p-3 space-y-1">
                    <div className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Best Thumbnail</div>
                    <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                      {nicheRecs.recommendations.thumbnail.style?.replace(/_/g, " ") || "—"}
                    </div>
                    <div className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                      {nicheRecs.recommendations.thumbnail.layout?.replace(/_/g, " ") || "—"} layout
                      {nicheRecs.recommendations.thumbnail.face_emotion && ` · ${nicheRecs.recommendations.thumbnail.face_emotion} face`}
                    </div>
                  </GlassCard>
                )}
                {/* Best Timing */}
                {nicheRecs.recommendations.timing && (
                  <GlassCard className="p-3 space-y-1">
                    <div className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Best Timing</div>
                    <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                      {nicheRecs.recommendations.timing.best_day_name || "—"}
                    </div>
                    <div className="text-[11px]" style={{ color: "var(--amber)" }}>
                      {nicheRecs.recommendations.timing.best_day_avg_vph.toLocaleString()} VPH
                      {nicheRecs.recommendations.timing.best_hour != null && ` · ${nicheRecs.recommendations.timing.best_hour}:00`}
                    </div>
                  </GlassCard>
                )}
              </div>
              {/* Top Topics */}
              {nicheRecs.recommendations.top_topics.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>Top topics:</span>
                  {nicheRecs.recommendations.top_topics.map((t) => (
                    <span key={t.topic} className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: "rgba(251,191,36,0.10)", color: "var(--amber)" }}>
                      {t.topic} ({t.avg_vph.toLocaleString()} VPH)
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Meta-Insights (Second-Order Distillation) */}
          {metaInsights?.status === "ok" && metaInsights.insights && (
            <GlassCard className="p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Zap size={14} style={{ color: "var(--violet)" }} />
                  <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Niche Meta-Analysis</h3>
                  <span className="text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>
                    {metaInsights.sample_size} videos · {metaInsights.generated_at ? new Date(metaInsights.generated_at).toLocaleDateString() : ""}
                  </span>
                </div>
                <button
                  onClick={() => metaAnalysisMutation.mutate()}
                  disabled={metaAnalysisMutation.isPending}
                  className="p-1 rounded hover:brightness-110 disabled:opacity-50"
                  style={{ color: "var(--text-muted)" }}
                >
                  {metaAnalysisMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                </button>
              </div>

              {metaInsights.insights.niche_summary && (
                <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {metaInsights.insights.niche_summary}
                </p>
              )}

              {metaInsights.insights.top_patterns && metaInsights.insights.top_patterns.length > 0 && (
                <div className="space-y-1.5">
                  <div className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Top Patterns</div>
                  {metaInsights.insights.top_patterns.map((p, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <span className="shrink-0 w-1 h-1 mt-1.5 rounded-full" style={{ background: p.confidence === "high" ? "var(--emerald)" : p.confidence === "medium" ? "var(--amber)" : "var(--text-muted)" }} />
                      <div>
                        <span style={{ color: "var(--text-primary)" }}>{p.pattern}</span>
                        <span className="ml-1.5" style={{ color: "var(--emerald)" }}>{p.performance}</span>
                        {p.recommendation && (
                          <span className="ml-1.5" style={{ color: "var(--text-muted)" }}>— {p.recommendation}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {metaInsights.insights.contrarian_findings && metaInsights.insights.contrarian_findings.length > 0 && (
                <div className="space-y-1">
                  <div className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Contrarian Findings</div>
                  {metaInsights.insights.contrarian_findings.map((f, i) => (
                    <div key={i} className="text-xs" style={{ color: "var(--text-secondary)" }}>⚡ {f}</div>
                  ))}
                </div>
              )}

              {metaInsights.insights.combination_insights && metaInsights.insights.combination_insights.length > 0 && (
                <div className="space-y-1">
                  <div className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Winning Combinations</div>
                  {metaInsights.insights.combination_insights.map((c, i) => (
                    <div key={i} className="text-xs" style={{ color: "var(--text-secondary)" }}>→ {c}</div>
                  ))}
                </div>
              )}
            </GlassCard>
          )}

          {/* Generate meta-insights button if none exist */}
          {(!metaInsights || metaInsights.status === "not_generated") && intelStats.distilled >= 20 && (
            <ActionButton
              variant="outline"
              onClick={() => metaAnalysisMutation.mutate()}
              disabled={metaAnalysisMutation.isPending}
            >
              {metaAnalysisMutation.isPending ? <Loader2 size={12} className="animate-spin mr-1" /> : <Zap size={12} className="mr-1" />}
              Generate Niche Meta-Analysis ({intelStats.distilled} videos)
            </ActionButton>
          )}
        </motion.div>
      )}

      </motion.div>
    </motion.div>
  );
}
