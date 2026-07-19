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
  Cell,
} from "recharts";
import {
  ArrowUpDown, RefreshCw, Loader2, Brain, TrendingUp, TrendingDown, Zap,
  Eye, BarChart3, Target, Clock, Users, ChevronDown, ChevronRight,
  ExternalLink, Film, Info,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatCard } from "@/components/ui/StatCard";
import { VerdictBadge } from "@/components/ui/VerdictBadge";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorCard } from "@/components/ui/ErrorCard";
import {
  getLearnings,
  syncYouTubeMetrics,
  getYouTubeSyncStatus,
  getAnalyticsOverview,
  getAnalyticsTimeline,
  getAnalyticsVideos,
  getFrameworkPerformance,
  getCompetitorBenchmark,
  getIntelligenceStats,
  getTopicInsights,
  getHookInsights,
  getThumbnailInsights,
  getTimingInsights,
  getIntelligenceRecommendations,
  getNicheMetaInsights,
  triggerMetaAnalysis,
  getStylePerformance,
  type StylePerformanceResponse,
} from "@/lib/api";
import { formatNumber, timeAgo } from "@/lib/utils";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: "easeOut" as const } },
};

type SortKey = "views" | "ctr" | "published_at";
type SortDir = "asc" | "desc";
type ChartMetric = "views" | "ctr" | "watch_time";
type ChartRange = 28 | 90;

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "--";
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "--";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
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

const CHART_METRICS: Record<ChartMetric, { label: string; dataKey: string; color: string; format: (v: number) => string }> = {
  views: { label: "Views", dataKey: "views", color: "var(--turquoise)", format: (v) => formatNumber(v) },
  ctr: { label: "CTR", dataKey: "ctr", color: "var(--gold)", format: (v) => `${v.toFixed(1)}%` },
  watch_time: { label: "Watch time", dataKey: "watch_time_minutes", color: "var(--purple)", format: (v) => `${Math.round(v)} min` },
};

const FRAMEWORK_COLORS = [
  "var(--turquoise)",
  "var(--gold)",
  "var(--purple)",
  "var(--orange)",
  "var(--green)",
  "var(--red)",
  "var(--yellow)",
];

// By-style panel — checklist §3.1 [U] / C31. Labels match schema.sql's column
// comments exactly: style_preset_id is the LOOK ENGINE preset (migration 097
// FK), render_style is the channel's declared LOOK ("animated"/"realistic",
// migration 089), script_profile is the editorial voice (migration 098),
// dominant clip model comes from generation_ledger (see analytics_by_style.py).
type StyleDimensionKey = keyof StylePerformanceResponse;
const STYLE_DIMENSIONS: { key: StyleDimensionKey; label: string }[] = [
  { key: "by_style_preset", label: "Look Engine" },
  { key: "by_render_style", label: "Channel Look" },
  { key: "by_script_profile", label: "Script Voice" },
  { key: "by_clip_model", label: "Clip Model" },
];

// Fail-safe formatting: every one of these takes possibly-null/zero backend
// fields and always returns a renderable string — never NaN, never a crash.
function pct1(v: number | null | undefined): string {
  return v === null || v === undefined || Number.isNaN(v) ? "--" : `${v.toFixed(1)}%`;
}

function pct0(v: number | null | undefined): string {
  return v === null || v === undefined || Number.isNaN(v) ? "--" : `${v.toFixed(0)}%`;
}

function money(v: number | null | undefined): string {
  return v === null || v === undefined || Number.isNaN(v) ? "--" : `$${v.toFixed(2)}`;
}

// Cost-per-1k-views: derived ONLY from the two totals the endpoint already
// serves (total_spend, total_views) — no new math source, per spec. Guards
// the zero-views case so this never divides by zero into Infinity/NaN.
function costPer1kViews(totalSpend: number | null | undefined, totalViews: number | null | undefined): string {
  if (!totalViews || totalViews <= 0 || totalSpend === null || totalSpend === undefined) return "--";
  return money(totalSpend / (totalViews / 1000));
}

function CollapsibleSection({
  icon,
  title,
  badge,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <GlassCard className="p-0 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-6 py-4 hover:bg-[rgba(255,255,255,0.02)] transition-colors"
      >
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            {title}
          </h2>
          {badge}
        </div>
        {open ? (
          <ChevronDown size={16} style={{ color: "var(--text-tertiary)" }} />
        ) : (
          <ChevronRight size={16} style={{ color: "var(--text-tertiary)" }} />
        )}
      </button>
      {open && <div className="px-6 pb-6">{children}</div>}
    </GlassCard>
  );
}

export default function AnalyticsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [sortKey, setSortKey] = useState<SortKey>("published_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [chartMetric, setChartMetric] = useState<ChartMetric>("views");
  const [chartRange, setChartRange] = useState<ChartRange>(28);

  // Channel analytics (real YouTube data)
  const { data: overview, isLoading: overviewLoading, error: overviewError } = useQuery({
    queryKey: ["analytics-overview"],
    queryFn: getAnalyticsOverview,
  });

  const { data: timeline, isLoading: timelineLoading } = useQuery({
    queryKey: ["analytics-timeline", chartRange],
    queryFn: () => getAnalyticsTimeline(chartRange),
  });

  const { data: channelVideos, isLoading: videosLoading } = useQuery({
    queryKey: ["analytics-videos"],
    queryFn: () => getAnalyticsVideos(50),
  });

  const { data: frameworks } = useQuery({
    queryKey: ["analytics-framework-performance"],
    queryFn: getFrameworkPerformance,
  });

  const { data: benchmark } = useQuery({
    queryKey: ["analytics-competitor-benchmark"],
    queryFn: getCompetitorBenchmark,
  });

  // Performance by creative choice (Look Engine / Channel Look / Script Voice /
  // Clip Model) — checklist §3.1 [U] / C31, reading C30's GET /api/analytics/by-style.
  const { data: stylePerformance, isLoading: styleLoading, error: styleError } = useQuery({
    queryKey: ["style-performance"],
    queryFn: getStylePerformance,
  });
  const [styleDimension, setStyleDimension] = useState<StyleDimensionKey>("by_style_preset");

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
      queryClient.invalidateQueries({ queryKey: ["analytics-overview"] });
      queryClient.invalidateQueries({ queryKey: ["analytics-timeline"] });
      queryClient.invalidateQueries({ queryKey: ["analytics-videos"] });
      queryClient.invalidateQueries({ queryKey: ["analytics-framework-performance"] });
      queryClient.invalidateQueries({ queryKey: ["analytics-competitor-benchmark"] });
      queryClient.invalidateQueries({ queryKey: ["videos"] });
    }
    prevRunning.current = syncRunning;
  }, [syncRunning, queryClient]);

  // Chart data from the daily channel timeseries
  const chartData = useMemo(() => {
    if (!timeline) return [];
    return timeline.map((p) => ({
      date: formatDate(p.date),
      views: p.views || 0,
      ctr: p.ctr,
      watch_time_minutes: p.watch_time_minutes,
    }));
  }, [timeline]);

  // Any video too fresh for YouTube to report CTR/duration yet?
  const hasFreshVideo = useMemo(() => {
    if (!channelVideos) return false;
    const cutoff = Date.now() - 48 * 3600 * 1000;
    return channelVideos.some(
      (v) => v.published_at && new Date(v.published_at).getTime() > cutoff && v.ctr === null
    );
  }, [channelVideos]);

  // Sorted table data
  const sortedVideos = useMemo(() => {
    if (!channelVideos) return [];
    return [...channelVideos].sort((a, b) => {
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
        case "published_at":
        default:
          aVal = a.published_at ? new Date(a.published_at).getTime() : 0;
          bVal = b.published_at ? new Date(b.published_at).getTime() : 0;
          break;
      }
      return sortDir === "desc" ? bVal - aVal : aVal - bVal;
    });
  }, [channelVideos, sortKey, sortDir]);

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

  // No channel connected: one clear card, nothing else.
  if (overview && !overview.connected) {
    return (
      <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
        <motion.div variants={item}>
          <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
            Analytics
          </h1>
        </motion.div>
        <motion.div variants={item}>
          <EmptyState
            icon={BarChart3}
            title="Connect your YouTube channel"
            description="Analytics shows the real performance of your channel: views, click-through rate, and watch time for every video. Connect YouTube to get started."
            actionLabel="Connect YouTube"
            actionHref="/settings/keys"
          />
        </motion.div>
      </motion.div>
    );
  }

  const channel = overview?.channel;
  const metric = CHART_METRICS[chartMetric];

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
      {/* Channel header */}
      <motion.div variants={item} className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-4">
          {channel?.thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={channel.thumbnail}
              alt={channel.name || "Channel"}
              className="w-14 h-14 rounded-full"
              style={{ border: "2px solid var(--turquoise)" }}
            />
          ) : (
            <div
              className="w-14 h-14 rounded-full flex items-center justify-center"
              style={{ background: "var(--bg-elevated)", border: "2px solid var(--turquoise)" }}
            >
              <Film size={22} style={{ color: "var(--turquoise)" }} />
            </div>
          )}
          <div>
            <h1 className="text-3xl font-display leading-tight" style={{ color: "var(--text-primary)" }}>
              {channel?.name || "Analytics"}
            </h1>
            <p className="text-xs font-mono mt-0.5" style={{ color: "var(--text-secondary)" }}>
              {formatNumber(channel?.subscribers ?? 0)} subscribers · {channel?.video_count ?? 0} videos on YouTube
            </p>
          </div>
        </div>
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
              Synced {timeAgo(syncStatus.last_run)}
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
                  Couldn&apos;t sync: {syncStatus.error}
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

      {/* Fresh-video data lag note */}
      {hasFreshVideo && (
        <motion.div variants={item}>
          <div
            className="rounded-xl px-4 py-3 flex items-center gap-2"
            style={{ background: "rgba(0,212,170,0.06)", border: "1px solid rgba(0,212,170,0.15)" }}
          >
            <Info size={14} style={{ color: "var(--turquoise)" }} className="shrink-0" />
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              YouTube takes 24-48 hours to report impressions, CTR, and view duration for new videos. Views update sooner.
            </span>
          </div>
        </motion.div>
      )}

      {/* KPI row */}
      {overview && (
        <motion.div variants={item} className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          <StatCard
            label="Views (28 days)"
            value={formatNumber(overview.views_28d)}
            detail={`${formatNumber(overview.total_views)} lifetime`}
            color="var(--turquoise)"
            icon={Eye}
          />
          <StatCard
            label="Watch Time (28d)"
            value={overview.watch_time_hours_28d !== null ? `${overview.watch_time_hours_28d}h` : "--"}
            detail="hours watched"
            color="var(--purple)"
            icon={Clock}
          />
          <StatCard
            label="Avg CTR"
            value={overview.avg_ctr !== null ? `${overview.avg_ctr.toFixed(1)}%` : "--"}
            detail={overview.avg_ctr === null ? "waiting on YouTube" : "of impressions clicked"}
            color={ctrColor(overview.avg_ctr)}
            icon={Target}
          />
          <StatCard
            label="Avg View Duration"
            value={formatDuration(overview.avg_view_duration_seconds)}
            detail={
              overview.avg_retention !== null
                ? `${overview.avg_retention.toFixed(0)}% of video watched`
                : "waiting on YouTube"
            }
            color="var(--gold)"
            icon={BarChart3}
          />
          <StatCard
            label="Subscribers"
            value={formatNumber(channel?.subscribers ?? 0)}
            detail={
              overview.subscribers_gained_28d !== 0
                ? `${overview.subscribers_gained_28d > 0 ? "+" : ""}${overview.subscribers_gained_28d} in 28 days`
                : "no change in 28 days"
            }
            color="var(--green)"
            icon={Users}
          />
        </motion.div>
      )}

      {/* Daily performance chart */}
      <motion.div variants={item}>
        <GlassCard className="p-6">
          <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
            <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Channel Performance
            </h2>
            <div className="flex items-center gap-2">
              <div className="flex rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
                {(Object.keys(CHART_METRICS) as ChartMetric[]).map((m) => (
                  <button
                    key={m}
                    onClick={() => setChartMetric(m)}
                    className="px-3 py-1.5 text-[11px] font-medium transition-colors"
                    style={{
                      background: chartMetric === m ? "rgba(0,212,170,0.12)" : "transparent",
                      color: chartMetric === m ? "var(--turquoise)" : "var(--text-tertiary)",
                    }}
                  >
                    {CHART_METRICS[m].label}
                  </button>
                ))}
              </div>
              <div className="flex rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
                {([28, 90] as ChartRange[]).map((r) => (
                  <button
                    key={r}
                    onClick={() => setChartRange(r)}
                    className="px-3 py-1.5 text-[11px] font-medium transition-colors"
                    style={{
                      background: chartRange === r ? "rgba(0,212,170,0.12)" : "transparent",
                      color: chartRange === r ? "var(--turquoise)" : "var(--text-tertiary)",
                    }}
                  >
                    {r}d
                  </button>
                ))}
              </div>
            </div>
          </div>
          {timelineLoading ? (
            <div className="h-72 flex items-center justify-center">
              <Spinner />
            </div>
          ) : chartData.length === 0 ? (
            <EmptyState
              icon={TrendingUp}
              title="No daily data yet"
              description="Click Sync YouTube to pull your channel's daily views, CTR, and watch time."
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
                    minTickGap={24}
                  />
                  <YAxis
                    tick={{ fill: "var(--text-tertiary)", fontSize: 11 }}
                    axisLine={false}
                    tickFormatter={(v: number) => metric.format(v)}
                    domain={[0, "auto"]}
                    width={56}
                  />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (!active || !payload?.[0]) return null;
                      const v = payload[0].value as number | null;
                      return (
                        <div
                          className="glass-card px-4 py-3 text-xs"
                          style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
                        >
                          <p className="font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
                            {label}
                          </p>
                          <p style={{ color: metric.color }}>
                            {metric.label}: {v !== null && v !== undefined ? metric.format(v) : "--"}
                          </p>
                        </div>
                      );
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey={metric.dataKey}
                    name={metric.label}
                    stroke={metric.color}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 5 }}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </GlassCard>
      </motion.div>

      {/* Videos on the channel (YouTube Studio style) */}
      <motion.div variants={item}>
        <GlassCard className="p-6 overflow-x-auto">
          <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            Videos
          </h2>
          {sortedVideos.length === 0 ? (
            <EmptyState
              icon={BarChart3}
              title="No videos on your channel yet"
              description="Once you publish to YouTube and hit Sync, every video on your channel shows up here with real stats."
            />
          ) : (
            <table className="w-full text-left">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {[
                    { label: "Video", key: null },
                    { label: "Published", key: "published_at" as SortKey },
                    { label: "Views", key: "views" as SortKey },
                    { label: "CTR%", key: "ctr" as SortKey },
                    { label: "Avg Duration", key: null },
                    { label: "Retention", key: null },
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
                {sortedVideos.map((v) => {
                  const verdict = getVerdict(v.ctr);
                  return (
                    <tr
                      key={v.id}
                      className="transition-colors hover:bg-[rgba(255,255,255,0.03)] cursor-pointer group"
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}
                      onClick={() => window.open(v.watch_url, "_blank", "noopener")}
                    >
                      <td className="py-3 px-3 max-w-[360px]">
                        <div className="flex items-center gap-3">
                          {v.thumbnail_url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={v.thumbnail_url}
                              alt=""
                              className="w-16 h-9 rounded object-cover shrink-0"
                              style={{ background: "var(--bg-elevated)" }}
                            />
                          ) : (
                            <div
                              className="w-16 h-9 rounded shrink-0 flex items-center justify-center"
                              style={{ background: "var(--bg-elevated)" }}
                            >
                              <Film size={14} style={{ color: "var(--text-tertiary)" }} />
                            </div>
                          )}
                          <div className="min-w-0">
                            <span
                              className="text-sm font-medium truncate block group-hover:text-[var(--turquoise)] transition-colors"
                              style={{ color: "var(--text-primary)" }}
                            >
                              {v.title || "Untitled"}
                              <ExternalLink size={11} className="inline ml-1.5 opacity-0 group-hover:opacity-60 transition-opacity" />
                            </span>
                            <div className="flex items-center gap-2 mt-0.5">
                              {v.privacy_status && v.privacy_status !== "public" && (
                                <span
                                  className="text-[10px] px-1.5 py-0.5 rounded-full font-mono"
                                  style={{ background: "rgba(212,168,82,0.12)", color: "var(--gold)" }}
                                >
                                  {v.privacy_status}
                                </span>
                              )}
                              {v.internal_video_id && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    router.push(`/pipeline/${v.internal_video_id}`);
                                  }}
                                  className="text-[10px] font-mono hover:brightness-125"
                                  style={{ color: "var(--text-tertiary)" }}
                                >
                                  made in StoryEngine →
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                          {formatDate(v.published_at)}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>
                          {formatNumber(v.views || 0)}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span
                          className="text-sm font-mono"
                          style={{ color: ctrColor(v.ctr) }}
                          title={v.ctr === null ? "YouTube hasn't reported this yet" : undefined}
                        >
                          {v.ctr !== null && v.ctr !== undefined ? `${v.ctr.toFixed(1)}%` : "--"}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span
                          className="text-xs font-mono"
                          style={{ color: "var(--text-secondary)" }}
                          title={v.avg_view_duration_seconds === null ? "YouTube hasn't reported this yet" : undefined}
                        >
                          {formatDuration(v.avg_view_duration_seconds)}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                          {v.avg_view_percentage !== null ? `${v.avg_view_percentage.toFixed(0)}%` : "--"}
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

      {/* Competitor strip */}
      {benchmark && benchmark.competitors.length > 0 && (
        <motion.div variants={item}>
          <GlassCard className="p-5">
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div className="flex items-center gap-6 flex-wrap">
                <div>
                  <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Our Avg CTR</span>
                  <p className="text-base font-mono font-bold" style={{ color: ctrColor(benchmark.channel_avg_ctr) }}>
                    {benchmark.channel_avg_ctr !== null ? `${benchmark.channel_avg_ctr.toFixed(1)}%` : "--"}
                  </p>
                </div>
                <div>
                  <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Our Views</span>
                  <p className="text-base font-mono font-bold" style={{ color: "var(--turquoise)" }}>
                    {formatNumber(benchmark.channel_total_views)}
                  </p>
                </div>
                <div className="h-8 w-px" style={{ background: "var(--border)" }} />
                {benchmark.competitors.slice(0, 3).map((c) => (
                  <div key={c.channel}>
                    <span className="text-[10px] uppercase tracking-wider truncate block max-w-[140px]" style={{ color: "var(--text-tertiary)" }}>
                      {c.channel}
                    </span>
                    <p className="text-base font-mono" style={{ color: "var(--gold)" }}>
                      {c.avg_vph !== null ? `${formatNumber(c.avg_vph)} VPH` : "--"}
                    </p>
                  </div>
                ))}
              </div>
              <button
                onClick={() => router.push("/discovery")}
                className="text-xs font-medium hover:brightness-125 transition-all"
                style={{ color: "var(--turquoise)" }}
              >
                See competitor ideas →
              </button>
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Framework performance: only shows once 2+ frameworks have real views */}
      {frameworks && frameworks.length >= 2 && (
        <motion.div variants={item}>
          <GlassCard className="p-6">
            <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
              What&apos;s Working (by framework)
            </h2>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={frameworks.map((f) => ({
                      name: f.framework.length > 20 ? f.framework.slice(0, 20) + "…" : f.framework,
                      fullName: f.framework,
                      avg_ctr: f.avg_ctr ?? 0,
                      video_count: f.video_count,
                      total_views: f.total_views,
                    }))}
                    layout="vertical"
                  >
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
                      {frameworks.map((_, i) => (
                        <Cell key={i} fill={FRAMEWORK_COLORS[i % FRAMEWORK_COLORS.length]} fillOpacity={0.8} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
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

      {/* Performance by creative choice — checklist §3.1 [U] / C31 */}
      <motion.div variants={item}>
        <GlassCard className="p-6 overflow-x-auto">
          <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
            <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Performance by Style
            </h2>
            <div className="flex rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
              {STYLE_DIMENSIONS.map((d) => (
                <button
                  key={d.key}
                  onClick={() => setStyleDimension(d.key)}
                  className="px-3 py-1.5 text-[11px] font-medium transition-colors whitespace-nowrap"
                  style={{
                    background: styleDimension === d.key ? "rgba(0,212,170,0.12)" : "transparent",
                    color: styleDimension === d.key ? "var(--turquoise)" : "var(--text-tertiary)",
                  }}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>

          {styleLoading ? (
            <div className="h-40 flex items-center justify-center">
              <Spinner />
            </div>
          ) : styleError ? (
            <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
              Couldn&apos;t load style performance right now.
            </p>
          ) : (stylePerformance?.[styleDimension]?.length ?? 0) === 0 ? (
            <EmptyState
              icon={BarChart3}
              title="No data yet"
              description="Once videos are made with more than one choice for this dimension, their performance compares here."
            />
          ) : (
            <table className="w-full text-left">
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  {["Choice", "Videos", "Avg CTR", "Avg Retention", "Total Views", "Total Spend", "Cost / 1k Views"].map((h) => (
                    <th
                      key={h}
                      className="pb-3 text-[11px] font-semibold uppercase tracking-wider whitespace-nowrap px-3"
                      style={{ color: "var(--text-tertiary)" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(stylePerformance?.[styleDimension] ?? []).map((r) => {
                  const noDataYet = r.synced_count === 0;
                  return (
                    <tr
                      key={r.choice}
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.04)", opacity: noDataYet ? 0.55 : 1 }}
                    >
                      <td className="py-3 px-3">
                        <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                          {r.choice}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                          {r.synced_count} / {r.video_count} synced
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        {noDataYet ? (
                          <span className="text-[11px] italic" style={{ color: "var(--text-tertiary)" }}>
                            no data yet
                          </span>
                        ) : (
                          <span className="text-sm font-mono font-semibold" style={{ color: ctrColor(r.avg_ctr) }}>
                            {pct1(r.avg_ctr)}
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-3">
                        {noDataYet ? (
                          <span className="text-[11px] italic" style={{ color: "var(--text-tertiary)" }}>
                            no data yet
                          </span>
                        ) : (
                          <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                            {pct0(r.avg_retention)}
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-3">
                        <span className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>
                          {formatNumber(r.total_views)}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                          {money(r.total_spend)}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                          {costPer1kViews(r.total_spend, r.total_views)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </GlassCard>
      </motion.div>

      {/* System Intelligence (learned patterns), collapsed by default */}
      {learnings && learnings.length > 0 && (
        <motion.div variants={item}>
          <CollapsibleSection
            icon={<Brain size={18} style={{ color: "var(--turquoise)" }} />}
            title="System Intelligence"
            badge={
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
            }
          >
            {(() => {
              const proven = learnings.filter((l) => l.confidence >= 60 && l.active);
              const avoid = learnings.filter((l) => l.confidence <= 30 && l.active);

              return (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
          </CollapsibleSection>
        </motion.div>
      )}

      {/* Niche Intelligence (from distilled competitor DNA), collapsed by default */}
      {intelStats && intelStats.distilled > 0 && (
        <motion.div variants={item}>
          <CollapsibleSection
            icon={<Brain size={16} style={{ color: "var(--amber)" }} />}
            title="Niche Intelligence"
            badge={
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full" style={{ background: "rgba(251,191,36,0.12)", color: "var(--amber)" }}>
                {intelStats.distilled} videos analyzed
              </span>
            }
          >
            <div className="space-y-4">
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
                    {nicheRecs.recommendations.thumbnail && (
                      <GlassCard className="p-3 space-y-1">
                        <div className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Best Thumbnail</div>
                        <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                          {nicheRecs.recommendations.thumbnail.style?.replace(/_/g, " ") || "n/a"}
                        </div>
                        <div className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                          {nicheRecs.recommendations.thumbnail.layout?.replace(/_/g, " ") || "n/a"} layout
                          {nicheRecs.recommendations.thumbnail.face_emotion && ` · ${nicheRecs.recommendations.thumbnail.face_emotion} face`}
                        </div>
                      </GlassCard>
                    )}
                    {nicheRecs.recommendations.timing && (
                      <GlassCard className="p-3 space-y-1">
                        <div className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Best Timing</div>
                        <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                          {nicheRecs.recommendations.timing.best_day_name || "n/a"}
                        </div>
                        <div className="text-[11px]" style={{ color: "var(--amber)" }}>
                          {nicheRecs.recommendations.timing.best_day_avg_vph.toLocaleString()} VPH
                          {nicheRecs.recommendations.timing.best_hour != null && ` · ${nicheRecs.recommendations.timing.best_hour}:00`}
                        </div>
                      </GlassCard>
                    )}
                  </div>
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
                              <span className="ml-1.5" style={{ color: "var(--text-muted)" }}>· {p.recommendation}</span>
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
            </div>
          </CollapsibleSection>
        </motion.div>
      )}
    </motion.div>
  );
}
