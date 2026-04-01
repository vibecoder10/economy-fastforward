"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { ArrowUpDown, RefreshCw, Loader2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { VerdictBadge } from "@/components/ui/VerdictBadge";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import { getVideos, syncYouTubeMetrics, getYouTubeSyncStatus, type VideoSummary } from "@/lib/api";
import { COMPLETED_STATUSES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";

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

function formatViews(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toString();
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "--";
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
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
          {p.name}: {p.dataKey === "views" ? formatViews(p.value) : `${p.value.toFixed(1)}%`}
        </p>
      ))}
    </div>
  );
}

export default function AnalyticsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [dateRange, setDateRange] = useState("12m");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const { data: allVideos, isLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
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
    }
    prevRunning.current = syncRunning;
  }, [syncRunning, queryClient]);

  // Filter to published/uploaded videos with some performance data
  const publishedVideos = useMemo(() => {
    if (!allVideos) return [];
    return allVideos.filter(
      (v) => COMPLETED_STATUSES.has(v.status || "") || v.views > 0 || v.ctr !== null
    );
  }, [allVideos]);

  // Filter by date range
  const filteredVideos = useMemo(() => {
    const now = new Date();
    let cutoff: Date;
    switch (dateRange) {
      case "30d":
        cutoff = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
        break;
      case "3m":
        cutoff = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000);
        break;
      case "12m":
      default:
        cutoff = new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000);
        break;
    }
    return publishedVideos.filter((v) => {
      if (!v.created_at) return true;
      return new Date(v.created_at) >= cutoff;
    });
  }, [publishedVideos, dateRange]);

  // Chart data: one point per video, sorted by date
  const chartData = useMemo(() => {
    return [...filteredVideos]
      .filter((v) => v.created_at)
      .sort((a, b) => new Date(a.created_at!).getTime() - new Date(b.created_at!).getTime())
      .map((v) => ({
        date: formatDate(v.created_at),
        views: v.views || 0,
        ctr: v.ctr ?? 0,
        title: v.video_title || "Untitled",
      }));
  }, [filteredVideos]);

  // Sorted table data
  const sortedVideos = useMemo(() => {
    return [...filteredVideos].sort((a, b) => {
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
  }, [filteredVideos, sortKey, sortDir]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
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
      {/* Header + Filter */}
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
          <FilterSelect
            options={[
              { value: "30d", label: "Last 30 days" },
              { value: "3m", label: "Last 3 months" },
              { value: "12m", label: "Last 12 months" },
            ]}
            value={dateRange}
            onChange={setDateRange}
          />
        </div>
      </motion.div>

      {/* Chart */}
      <motion.div variants={item}>
        <GlassCard className="p-6">
          <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            Views &amp; CTR Over Time
          </h2>
          {chartData.length === 0 ? (
            <div
              className="h-72 flex items-center justify-center rounded-xl"
              style={{ background: "rgba(255,255,255,0.02)" }}
            >
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                No published videos with performance data yet.
              </p>
            </div>
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
                    tickFormatter={formatViews}
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

      {/* Data table */}
      <motion.div variants={item}>
        <GlassCard className="p-6 overflow-x-auto">
          <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            Video Performance
          </h2>
          {sortedVideos.length === 0 ? (
            <div
              className="rounded-xl p-8 text-center"
              style={{ background: "rgba(255,255,255,0.02)" }}
            >
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                No published videos to analyze.
              </p>
            </div>
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
                          {formatViews(v.views || 0)}
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
