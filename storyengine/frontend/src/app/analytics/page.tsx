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
  type VideoSummary,
  type LearningRecord,
  type AnalyticsOverview,
  type CTRTimelinePoint,
  type FrameworkPerformance,
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
      <div className="p-8 text-center">
        <p className="text-sm mb-2" style={{ color: "var(--red)" }}>
          Unable to load analytics data. The server may need to be restarted.
        </p>
        <button
          onClick={() => window.location.reload()}
          className="text-xs px-4 py-2 rounded-lg"
          style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
        >
          Retry
        </button>
      </div>
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
      </motion.div>
    </motion.div>
  );
}
