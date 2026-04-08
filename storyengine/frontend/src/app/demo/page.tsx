"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutGrid,
  List,
  BarChart3,
  ChevronRight,
  Film,
  Eye,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";
import Link from "next/link";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatCard } from "@/components/ui/StatCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { Spinner } from "@/components/ui/spinner";
import { ActionButton } from "@/components/ui/ActionButton";
import { getStageLabel } from "@/lib/constants";
import { formatNumber } from "@/lib/utils";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

interface DemoVideo {
  id: string;
  video_title: string;
  status: string;
  views: number;
  ctr: number | null;
  avg_retention: number | null;
  thumbnail_url: string | null;
}

interface DemoDashboard {
  active_bots: number;
  pending_review: number;
  pipeline_distribution: Record<string, number>;
  cost_today: number;
  total_videos: number;
  recent_videos: DemoVideo[];
}

interface DemoAnalytics {
  total_videos: number;
  total_views: number;
  avg_ctr: number;
  avg_retention: number;
  published_videos: number;
  ctr_timeline: { video_title: string; ctr: number; views: number; date: string }[];
  framework_performance: { framework: string; video_count: number; avg_ctr: number }[];
}

interface DemoPipeline {
  stages: { name: string; count: number }[];
  recent_activity: { bot: string; video_title: string; status: string; message: string }[];
  videos: DemoVideo[];
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
const fetchDemo = <T,>(path: string) => fetch(`${API}${path}`).then((r) => r.json() as Promise<T>);

const STAGE_COLORS: Record<string, string> = {
  idea_logged: "var(--text-secondary)",
  ready_for_scripting: "var(--turquoise)",
  ready_for_voice: "var(--turquoise)",
  ready_for_images: "var(--purple)",
  ready_for_thumbnail: "var(--gold)",
  ready_to_render: "var(--orange)",
  done: "var(--green)",
};

const FW_COLORS = ["var(--turquoise)", "var(--gold)", "var(--purple)", "var(--orange)", "var(--green)"];

export default function DemoPage() {
  const [tab, setTab] = useState<"dashboard" | "pipeline" | "analytics">("dashboard");

  const { data: dashboard, isLoading: dashLoading } = useQuery({
    queryKey: ["demo-dashboard"],
    queryFn: () => fetchDemo<DemoDashboard>("/api/demo/dashboard"),
  });

  const { data: analytics, isLoading: analyticsLoading } = useQuery({
    queryKey: ["demo-analytics"],
    queryFn: () => fetchDemo<DemoAnalytics>("/api/demo/analytics"),
  });

  const { data: pipeline, isLoading: pipelineLoading } = useQuery({
    queryKey: ["demo-pipeline"],
    queryFn: () => fetchDemo<DemoPipeline>("/api/demo/pipeline"),
  });

  const isLoading = (tab === "dashboard" && dashLoading) || (tab === "analytics" && analyticsLoading) || (tab === "pipeline" && pipelineLoading);

  const tabs = [
    { id: "dashboard" as const, label: "Dashboard", icon: LayoutGrid },
    { id: "pipeline" as const, label: "Pipeline", icon: List },
    { id: "analytics" as const, label: "Analytics", icon: BarChart3 },
  ];

  return (
    <motion.div className="space-y-6 max-w-[1100px] mx-auto" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item}>
        <div className="flex items-center justify-between">
          <div>
            <StatusPill label="DEMO MODE" color="gold" pulse />
            <h1 className="text-3xl font-display mt-2" style={{ color: "var(--text-primary)" }}>
              StoryEngine Demo
            </h1>
            <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
              Explore the platform with sample data. No account needed.
            </p>
          </div>
          <Link href="/login">
            <ActionButton icon={Zap}>Get Started</ActionButton>
          </Link>
        </div>
      </motion.div>

      {/* Tab Bar */}
      <motion.div variants={item}>
        <div className="flex gap-1 rounded-lg p-1" style={{ background: "rgba(255,255,255,0.03)" }}>
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className="flex items-center gap-2 px-4 py-2 rounded-md text-xs font-medium transition-colors"
              style={{
                background: tab === t.id ? "rgba(0,212,170,0.12)" : "transparent",
                color: tab === t.id ? "var(--turquoise)" : "var(--text-secondary)",
              }}
            >
              <t.icon size={14} />
              {t.label}
            </button>
          ))}
        </div>
      </motion.div>

      {isLoading && (
        <div className="flex items-center justify-center h-48">
          <Spinner size="lg" />
        </div>
      )}

      {/* Dashboard Tab */}
      {tab === "dashboard" && dashboard && !dashLoading && (
        <>
          <motion.div variants={item} className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Total Videos" value={String(dashboard.total_videos)} color="var(--turquoise)" icon={Film} />
            <StatCard label="Active Bots" value={String(dashboard.active_bots)} color="var(--green)" />
            <StatCard label="Pending Review" value={String(dashboard.pending_review)} color="var(--gold)" />
            <StatCard label="Cost Today" value={`$${dashboard.cost_today.toFixed(2)}`} color="var(--orange)" />
          </motion.div>

          <motion.div variants={item}>
            <GlassCard className="!p-5">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
                Pipeline Distribution
              </h2>
              <div className="flex items-end gap-2 h-32">
                {Object.entries(dashboard.pipeline_distribution).map(([stage, count]) => {
                  const maxCount = Math.max(...Object.values(dashboard.pipeline_distribution), 1);
                  const height = (count / maxCount) * 100;
                  return (
                    <div key={stage} className="flex-1 flex flex-col items-center gap-1">
                      <span className="text-[10px] font-mono" style={{ color: STAGE_COLORS[stage] || "var(--text-tertiary)" }}>
                        {count}
                      </span>
                      <div
                        className="w-full rounded-t-md transition-all"
                        style={{
                          height: `${Math.max(height, 4)}%`,
                          background: STAGE_COLORS[stage] || "var(--text-tertiary)",
                          opacity: 0.7,
                        }}
                      />
                      <span className="text-[8px] text-center" style={{ color: "var(--text-tertiary)" }}>
                        {getStageLabel(stage)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </GlassCard>
          </motion.div>

          <motion.div variants={item}>
            <GlassCard className="!p-5">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>
                Recent Videos
              </h2>
              <div className="space-y-2">
                {dashboard.recent_videos.map((v) => (
                  <div key={v.id} className="flex items-center justify-between py-2 px-3 rounded-lg" style={{ background: "rgba(255,255,255,0.02)" }}>
                    <div className="flex items-center gap-3">
                      <Film size={14} style={{ color: STAGE_COLORS[v.status] || "var(--text-tertiary)" }} />
                      <span className="text-sm" style={{ color: "var(--text-primary)" }}>{v.video_title}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <StatusPill label={getStageLabel(v.status)} color={v.status === "done" ? "green" : "teal"} size="sm" />
                      {v.views > 0 && (
                        <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>{formatNumber(v.views)} views</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </GlassCard>
          </motion.div>
        </>
      )}

      {/* Pipeline Tab */}
      {tab === "pipeline" && pipeline && !pipelineLoading && (
        <>
          <motion.div variants={item}>
            <GlassCard className="!p-5">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
                Pipeline Stages
              </h2>
              <div className="space-y-2">
                {pipeline.stages.filter((s) => s.count > 0).map((s) => (
                  <div key={s.name} className="flex items-center justify-between py-2 px-3 rounded-lg" style={{ background: "rgba(255,255,255,0.02)" }}>
                    <span className="text-sm" style={{ color: "var(--text-primary)" }}>{getStageLabel(s.name)}</span>
                    <span className="text-sm font-mono font-semibold" style={{ color: STAGE_COLORS[s.name] || "var(--turquoise)" }}>{s.count}</span>
                  </div>
                ))}
              </div>
            </GlassCard>
          </motion.div>

          <motion.div variants={item}>
            <GlassCard className="!p-5">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>
                Recent Activity
              </h2>
              <div className="space-y-2">
                {pipeline.recent_activity.map((a, i) => (
                  <div key={i} className="flex items-center gap-3 py-2">
                    <span className="w-2 h-2 rounded-full" style={{ background: a.status === "completed" ? "var(--green)" : "var(--turquoise)" }} />
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                      <strong style={{ color: "var(--text-primary)" }}>{a.bot}</strong> — {a.message}
                    </span>
                  </div>
                ))}
              </div>
            </GlassCard>
          </motion.div>
        </>
      )}

      {/* Analytics Tab */}
      {tab === "analytics" && analytics && !analyticsLoading && (
        <>
          <motion.div variants={item} className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Total Videos" value={String(analytics.total_videos)} color="var(--turquoise)" icon={Film} />
            <StatCard label="Total Views" value={formatNumber(analytics.total_views)} color="var(--purple)" icon={Eye} />
            <StatCard label="Avg CTR" value={`${analytics.avg_ctr}%`} color="var(--green)" icon={Target} />
            <StatCard label="Avg Retention" value={`${analytics.avg_retention}%`} color="var(--gold)" icon={TrendingUp} />
          </motion.div>

          <motion.div variants={item}>
            <GlassCard className="!p-6">
              <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>CTR & Views</h2>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={analytics.ctr_timeline.map((p) => ({ ...p, date: new Date(p.date).toLocaleDateString("en-US", { month: "short", day: "numeric" }) }))}>
                    <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} />
                    <YAxis yAxisId="v" tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickFormatter={(v: number) => formatNumber(v)} />
                    <YAxis yAxisId="c" orientation="right" tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickFormatter={(v: number) => `${v}%`} />
                    <Tooltip contentStyle={{ background: "var(--bg-deep)", border: "1px solid var(--border)", fontSize: 12 }} />
                    <Line yAxisId="v" type="monotone" dataKey="views" name="Views" stroke="var(--turquoise)" strokeWidth={2} dot={{ r: 4, fill: "var(--turquoise)" }} />
                    <Line yAxisId="c" type="monotone" dataKey="ctr" name="CTR %" stroke="var(--gold)" strokeWidth={2} strokeDasharray="5 5" dot={{ r: 4, fill: "var(--gold)" }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>
          </motion.div>

          <motion.div variants={item}>
            <GlassCard className="!p-6">
              <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>Framework Effectiveness</h2>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={analytics.framework_performance} layout="vertical">
                    <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} axisLine={false} tickFormatter={(v: number) => `${v}%`} />
                    <YAxis dataKey="framework" type="category" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} width={130} />
                    <Tooltip contentStyle={{ background: "var(--bg-deep)", border: "1px solid var(--border)", fontSize: 12 }} />
                    <Bar dataKey="avg_ctr" name="Avg CTR" radius={[0, 4, 4, 0]}>
                      {analytics.framework_performance.map((_, i) => (
                        <Cell key={i} fill={FW_COLORS[i % FW_COLORS.length]} fillOpacity={0.8} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>
          </motion.div>
        </>
      )}

      {/* CTA */}
      <motion.div variants={item}>
        <GlassCard className="!p-6 text-center">
          <h2 className="text-lg font-display" style={{ color: "var(--text-primary)" }}>
            Ready to build your own production pipeline?
          </h2>
          <p className="text-xs mt-1 mb-4" style={{ color: "var(--text-secondary)" }}>
            Sign up and create your first AI video in under 5 minutes.
          </p>
          <Link href="/login">
            <ActionButton icon={ChevronRight}>Start Free Trial</ActionButton>
          </Link>
        </GlassCard>
      </motion.div>
    </motion.div>
  );
}
