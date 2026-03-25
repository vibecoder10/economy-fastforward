"use client";

import { useState } from "react";
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
import { GlassCard } from "@/components/ui/GlassCard";
import { VerdictBadge } from "@/components/ui/VerdictBadge";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { MOCK_VIDEOS, MOCK_ANALYTICS_DATA, MOCK_INSIGHTS } from "@/lib/mock-data";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: "easeOut" as const } },
};

const publishedVideos = MOCK_VIDEOS.filter((v) => v.verdict);

function formatViews(n: number) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(0)}K`;
  return n.toString();
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload) return null;
  return (
    <div
      className="glass-card px-4 py-3 text-xs"
      style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
    >
      <p className="font-semibold mb-1" style={{ color: "var(--text-primary)" }}>{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {p.dataKey === "views" ? formatViews(p.value) : `${p.value}%`}
        </p>
      ))}
    </div>
  );
}

export default function AnalyticsPage() {
  const [dateRange, setDateRange] = useState("12m");

  return (
    <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
      {/* Header + Filter */}
      <motion.div variants={item} className="flex items-center justify-between gap-4 flex-wrap">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Analytics
        </h1>
        <FilterSelect
          options={[
            { value: "3m", label: "Last 3 months" },
            { value: "6m", label: "Last 6 months" },
            { value: "12m", label: "Last 12 months" },
          ]}
          value={dateRange}
          onChange={setDateRange}
        />
      </motion.div>

      {/* Chart */}
      <motion.div variants={item}>
        <GlassCard className="p-6">
          <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            Strategic Engagement Metrics
          </h2>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={MOCK_ANALYTICS_DATA}>
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
                  tickFormatter={(v) => `${v}%`}
                />
                <Tooltip content={<CustomTooltip />} />
                <Legend
                  wrapperStyle={{ fontSize: 11, color: "var(--text-secondary)" }}
                />
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
        </GlassCard>
      </motion.div>

      {/* Data table */}
      <motion.div variants={item}>
        <GlassCard className="p-6 overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                {["#", "Title", "Upload Date", "Views", "CTR%", "Retention%", "Watch Time", "Verdict"].map((h) => (
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
              {publishedVideos.map((v, i) => (
                <tr
                  key={v.id}
                  className="transition-colors hover:bg-[var(--bg-surface)] group"
                  style={{ borderBottom: "1px solid var(--border-subtle)" }}
                >
                  <td className="py-3 px-3">
                    <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                      {i + 1}
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    <span
                      className="text-sm font-medium group-hover:text-[var(--turquoise)] transition-colors"
                      style={{ color: "var(--text-primary)", borderLeft: "2px solid transparent" }}
                    >
                      {v.title}
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                      {v.uploadDate}
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    <span className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>
                      {formatViews(v.views || 0)}
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    <span className="text-sm font-mono" style={{ color: "var(--gold)" }}>
                      {v.ctr?.toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    <span className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>
                      {v.retention}%
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                      {v.watchTimeHrs?.toLocaleString()}h
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    {v.verdict && <VerdictBadge verdict={v.verdict} />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      </motion.div>

      {/* Insight cards */}
      <motion.div variants={item} className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {MOCK_INSIGHTS.map((insight) => (
          <GlassCard key={insight.title} className="p-5" style={{ borderLeftColor: insight.color, borderLeftWidth: 3 }}>
            <p className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: insight.color }}>
              {insight.category}
            </p>
            <h3 className="text-sm font-semibold mb-2 font-body" style={{ color: "var(--text-primary)" }}>
              {insight.title}
            </h3>
            <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
              {insight.description}
            </p>
            <div className="flex items-center gap-3">
              <span className="text-lg font-bold font-mono" style={{ color: insight.color }}>
                {insight.stat}
              </span>
              <span className="text-[10px] uppercase" style={{ color: "var(--text-tertiary)" }}>
                {insight.statLabel}
              </span>
            </div>
          </GlassCard>
        ))}
      </motion.div>
    </motion.div>
  );
}
