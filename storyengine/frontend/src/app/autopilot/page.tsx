"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  Brain,
  Power,
  Calendar,
  TrendingUp,
  BarChart3,
  Lightbulb,
  ChevronRight,
  Check,
  X,
  FileText,
  DollarSign,
} from "lucide-react";
import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { StatCard } from "@/components/ui/StatCard";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { ActionButton } from "@/components/ui/ActionButton";
import {
  getAutopilotSummary,
  toggleAutopilot,
  updateAutopilotConfig,
  getAgentStats,
  AutopilotSummary,
} from "@/lib/api";

// Default weights for display when API doesn't return them
const DEFAULT_WEIGHTS = {
  competitor_vph: 0.55,
  timing_freshness: 0.45,
};

const DEFAULT_THRESHOLDS = {
  min_confidence_score: 60,
  min_competitor_vph: 50,
  max_idea_age_days: 7,
  ctr_success_threshold: 4.0,
  ctr_failure_threshold: 2.5,
};

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08 } },
};

const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const CATEGORY_COLORS: Record<string, string> = {
  title: "turquoise",
  hook: "orange",
  thumbnail: "purple",
  retention: "green",
  framework: "gold",
};

export default function AutopilotPage() {
  const [data, setData] = useState<AutopilotSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isEnabled, setIsEnabled] = useState(true);
  const [editingTarget, setEditingTarget] = useState(false);
  const [targetValue, setTargetValue] = useState(15);
  const [savingTarget, setSavingTarget] = useState(false);

  const { data: agentStats } = useQuery({
    queryKey: ["agent-stats"],
    queryFn: getAgentStats,
  });

  // Fetch data on mount
  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        const summary = await getAutopilotSummary();
        setData(summary);
        setIsEnabled(summary.state.enabled);
        setTargetValue(summary.config.videos_per_month);
      } catch (err) {
        console.error("Error fetching autopilot data:", err);
        setError("Failed to load autopilot data");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  const handleToggle = async () => {
    const newEnabled = !isEnabled;
    setIsEnabled(newEnabled);
    try {
      await toggleAutopilot(newEnabled);
    } catch (err) {
      console.error("Error toggling autopilot:", err);
      setIsEnabled(!newEnabled); // Revert on error
    }
  };

  const handleSaveTarget = async () => {
    setSavingTarget(true);
    try {
      await updateAutopilotConfig(targetValue);
      setEditingTarget(false);
      // Refresh data
      const summary = await getAutopilotSummary();
      setData(summary);
    } catch (err) {
      console.error("Error saving target:", err);
    } finally {
      setSavingTarget(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Autopilot
        </h1>
        <div className="animate-pulse space-y-4">
          <div className="h-40 rounded-2xl" style={{ background: "rgba(255,255,255,0.03)" }} />
          <div className="h-60 rounded-2xl" style={{ background: "rgba(255,255,255,0.03)" }} />
          <div className="h-40 rounded-2xl" style={{ background: "rgba(255,255,255,0.03)" }} />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="space-y-6">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Autopilot
        </h1>
        <GlassCard className="border-red-500/20">
          <p className="text-sm" style={{ color: "var(--red)" }}>
            {error || "Failed to load data"}
          </p>
        </GlassCard>
      </div>
    );
  }

  const { state, config, learnings } = data;
  const weights = Object.keys(config.weights).length > 0 ? config.weights : DEFAULT_WEIGHTS;
  const thresholds = Object.keys(config.thresholds).length > 0 ? config.thresholds : DEFAULT_THRESHOLDS;
  const cadenceProgress = ((state.videos_produced % config.videos_per_month) / config.videos_per_month) * 100;

  return (
    <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
            Autopilot
          </h1>
          {isEnabled && (
            <StatusPill label="Active" color="turquoise" pulse size="md" />
          )}
        </div>
        <button
          onClick={handleToggle}
          className="relative flex items-center gap-2.5 rounded-full px-6 py-2.5 text-sm font-semibold transition-all duration-300"
          style={{
            background: isEnabled
              ? "linear-gradient(135deg, rgba(0, 212, 170, 0.25), rgba(0, 212, 170, 0.1))"
              : "linear-gradient(135deg, rgba(255, 77, 106, 0.25), rgba(255, 77, 106, 0.1))",
            color: isEnabled ? "var(--turquoise)" : "var(--red)",
            border: isEnabled
              ? "1px solid rgba(0, 212, 170, 0.3)"
              : "1px solid rgba(255, 77, 106, 0.3)",
            boxShadow: isEnabled
              ? "0 0 20px rgba(0, 212, 170, 0.15)"
              : "0 0 20px rgba(255, 77, 106, 0.15)",
          }}
        >
          <Power size={16} />
          {isEnabled ? "ON" : "OFF"}
        </button>
      </motion.div>

      {/* Status Card */}
      <motion.div variants={item}>
        <GlassCard>
          <div className="flex items-start gap-4">
            <div className="relative flex h-12 w-12 items-center justify-center rounded-xl"
              style={{ background: isEnabled ? "rgba(0, 212, 170, 0.1)" : "rgba(255,255,255,0.05)" }}
            >
              {isEnabled && (
                <motion.div
                  animate={{ scale: [1, 1.3, 1], opacity: [0.4, 0.1, 0.4] }}
                  transition={{ repeat: Infinity, duration: 2.5 }}
                  className="absolute inset-0 rounded-xl"
                  style={{ background: "rgba(0, 212, 170, 0.15)" }}
                />
              )}
              <Brain size={24} style={{ color: isEnabled ? "var(--turquoise)" : "var(--text-secondary)" }} />
            </div>
            <div className="flex-1">
              <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
                {isEnabled ? "Autopilot Active" : "Autopilot Disabled"}
              </h2>
              <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
                {isEnabled
                  ? `Next production slot in ${state.days_until_next} days (${state.next_production_date})`
                  : "Enable autopilot to let AI manage video production"}
              </p>
            </div>
          </div>
        </GlassCard>
      </motion.div>

      {/* Stat Cards */}
      <motion.div variants={item} className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Videos Produced"
          value={state.videos_produced}
          color="var(--turquoise)"
          icon={Brain}
        />
        <StatCard
          label="Avg CTR"
          value={`${state.channel_avg_ctr}%`}
          color="var(--green)"
          icon={TrendingUp}
        />
        <div className="glass-card p-5 relative overflow-hidden"
          style={{ borderColor: "rgba(212, 168, 82, 0.2)" }}
        >
          <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: "var(--gold)" }} />
          {editingTarget ? (
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wider mb-2" style={{ color: "var(--gold)" }}>
                Target / Month
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={targetValue}
                  onChange={(e) => setTargetValue(parseInt(e.target.value) || 1)}
                  min={1}
                  max={30}
                  className="w-16 rounded-lg px-2 py-1 text-xl font-semibold font-body focus:outline-none"
                  style={{
                    background: "rgba(255,255,255,0.05)",
                    border: "1px solid rgba(212, 168, 82, 0.3)",
                    color: "var(--text-primary)",
                  }}
                  autoFocus
                />
                <button
                  onClick={handleSaveTarget}
                  disabled={savingTarget}
                  className="rounded-lg p-1.5 transition-colors"
                  style={{ color: "var(--green)", background: "rgba(0, 230, 138, 0.1)" }}
                >
                  <Check size={16} />
                </button>
                <button
                  onClick={() => {
                    setEditingTarget(false);
                    setTargetValue(config.videos_per_month);
                  }}
                  className="rounded-lg p-1.5 transition-colors"
                  style={{ color: "var(--red)", background: "rgba(255, 77, 106, 0.1)" }}
                >
                  <X size={16} />
                </button>
              </div>
            </div>
          ) : (
            <button onClick={() => setEditingTarget(true)} className="group text-left w-full">
              <p className="text-[11px] font-medium uppercase tracking-wider mb-1" style={{ color: "var(--gold)" }}>
                Target / Month
              </p>
              <p className="text-2xl font-semibold font-body transition-colors"
                style={{ color: "var(--text-primary)" }}>
                {config.videos_per_month}
              </p>
              <p className="text-[11px] mt-1 font-mono" style={{ color: "var(--text-secondary)" }}>
                click to edit
              </p>
            </button>
          )}
        </div>
      </motion.div>

      {/* Script Quality */}
      {agentStats && agentStats.total_scripts > 0 && (
        <motion.div variants={item}>
          <GlassCard>
            <h2 className="text-[11px] font-semibold uppercase tracking-wider mb-4"
              style={{ color: "var(--text-secondary)" }}>
              Script Quality
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wider mb-1"
                  style={{ color: "var(--text-secondary)" }}>
                  Avg Hook Score
                </p>
                <p className="text-2xl font-semibold font-body"
                  style={{ color: agentStats.avg_hook_score >= 70 ? "var(--green)" : "var(--orange)" }}>
                  {agentStats.avg_hook_score.toFixed(0)}
                </p>
              </div>
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wider mb-1"
                  style={{ color: "var(--text-secondary)" }}>
                  Avg Body Score
                </p>
                <p className="text-2xl font-semibold font-body"
                  style={{ color: agentStats.avg_body_score >= 70 ? "var(--green)" : "var(--orange)" }}>
                  {agentStats.avg_body_score.toFixed(0)}
                </p>
              </div>
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wider mb-1"
                  style={{ color: "var(--text-secondary)" }}>
                  Scripts Processed
                </p>
                <p className="text-2xl font-semibold font-body" style={{ color: "var(--text-primary)" }}>
                  {agentStats.total_scripts}
                </p>
              </div>
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wider mb-1"
                  style={{ color: "var(--text-secondary)" }}>
                  Total Cost
                </p>
                <p className="text-2xl font-semibold font-body" style={{ color: "var(--text-primary)" }}>
                  ${agentStats.total_cost.toFixed(2)}
                </p>
              </div>
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Top Recommendations */}
      {data?.candidates && data.candidates.length > 0 && (
        <motion.div variants={item}>
          <GlassCard>
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider"
                style={{ color: "var(--text-secondary)" }}>
                Top Recommendations
              </h2>
              <Link href="/competitors" className="text-xs font-medium transition-colors hover:brightness-125"
                style={{ color: "var(--turquoise)" }}>
                View All
                <ChevronRight size={12} className="inline ml-0.5" />
              </Link>
            </div>
            <div className="space-y-2">
              {data.candidates.slice(0, 3).map((candidate: any, i: number) => {
                const medal = ["\u{1F3C6}", "\u{1F948}", "\u{1F949}"][i];
                const videoId = candidate.url?.match(/(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/)?.[1];
                const thumbUrl = videoId ? `https://img.youtube.com/vi/${videoId}/mqdefault.jpg` : null;

                return (
                  <Link
                    key={candidate.id}
                    href="/competitors"
                    className="flex items-center gap-4 p-3 rounded-xl transition-all duration-200"
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
                    <span className="text-lg">{medal}</span>
                    {thumbUrl && (
                      <img src={thumbUrl} alt="" className="w-20 h-12 rounded-lg object-cover shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>
                        {candidate.title}
                      </p>
                      <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                        {candidate.source} · {Math.round(candidate.hours_old)}h ago
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-sm font-bold" style={{ color: "var(--turquoise)" }}>
                        {candidate.confidence.toFixed(0)}
                      </p>
                      <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
                        conf
                      </p>
                    </div>
                  </Link>
                );
              })}
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Confidence Weights */}
      <motion.div variants={item}>
        <GlassCard>
          <div className="flex items-center gap-2 mb-1">
            <BarChart3 size={16} style={{ color: "var(--turquoise)" }} />
            <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Confidence Weights
            </h2>
          </div>
          <p className="text-[11px] mb-5" style={{ color: "var(--text-secondary)" }}>
            How candidates are scored — VPH measures viral potential, Freshness measures topic timeliness
          </p>

          <div className="space-y-4">
            {Object.entries(weights).map(([key, value]) => (
              <div key={key}>
                <div className="flex items-center justify-between text-xs mb-1.5">
                  <span style={{ color: "var(--text-secondary)" }}>
                    {key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                  </span>
                  <span className="font-mono font-medium" style={{ color: "var(--turquoise)" }}>
                    {(Number(value) * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                  <motion.div
                    className="h-full rounded-full"
                    style={{ background: "var(--turquoise)" }}
                    initial={{ width: 0 }}
                    animate={{ width: `${Number(value) * 100}%` }}
                    transition={{ duration: 1, ease: "easeOut" as const }}
                  />
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      </motion.div>

      {/* Learned Patterns */}
      <motion.div variants={item}>
        <GlassCard>
          <div className="flex items-center gap-2 mb-1">
            <Lightbulb size={16} style={{ color: "var(--turquoise)" }} />
            <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Learned Patterns
            </h2>
          </div>
          <p className="text-[11px] mb-5" style={{ color: "var(--text-secondary)" }}>
            Patterns discovered from video performance — used to guide future decisions
          </p>

          {learnings.length === 0 ? (
            <div className="rounded-xl p-5 text-center"
              style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)" }}>
              <Lightbulb size={24} className="mx-auto mb-2" style={{ color: "var(--text-secondary)", opacity: 0.4 }} />
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                No learnings yet. Patterns will be extracted after videos are published.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {learnings.map((learning) => (
                <div
                  key={learning.id}
                  className="flex items-center justify-between rounded-xl px-4 py-3 transition-all duration-200"
                  style={{
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.05)",
                  }}
                >
                  <div className="flex-1 min-w-0">
                    <span className="text-sm block truncate" style={{ color: "var(--text-primary)" }}>
                      {learning.pattern}
                    </span>
                    <div className="flex items-center gap-2 mt-1">
                      <StatusPill
                        label={learning.category}
                        color={CATEGORY_COLORS[learning.category] || "turquoise"}
                        size="sm"
                      />
                      <span className="text-[11px] font-mono" style={{ color: "var(--text-secondary)" }}>
                        {Math.round(learning.confidence)}% confidence
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 ml-3 shrink-0">
                    {learning.effect && (
                      <span className="text-sm font-medium" style={{ color: "var(--green)" }}>
                        {learning.effect}
                      </span>
                    )}
                    <span className="text-[11px] font-mono" style={{ color: "var(--text-secondary)" }}>
                      n={learning.sample_size}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {learnings.length > 0 && (
            <Link
              href="/autopilot/learnings"
              className="mt-5 flex items-center justify-center gap-1 text-xs font-medium transition-colors hover:brightness-125"
              style={{ color: "var(--turquoise)" }}
            >
              View All Learnings
              <ChevronRight size={14} />
            </Link>
          )}
        </GlassCard>
      </motion.div>

      {/* Production Cadence */}
      <motion.div variants={item}>
        <GlassCard>
          <div className="flex items-center gap-2 mb-5">
            <Calendar size={16} style={{ color: "var(--turquoise)" }} />
            <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Production Cadence
            </h2>
          </div>

          <div className="flex items-center gap-6">
            <ProgressRing
              value={cadenceProgress}
              size={90}
              color="var(--turquoise)"
              strokeWidth={6}
            >
              <span className="text-lg font-semibold" style={{ color: "var(--turquoise)" }}>
                {state.videos_produced % config.videos_per_month}
              </span>
              <span className="text-[9px] uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
                / {config.videos_per_month}
              </span>
            </ProgressRing>

            <div className="flex-1 grid grid-cols-2 gap-4">
              <div className="rounded-xl p-3"
                style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)" }}>
                <p className="text-2xl font-semibold font-body" style={{ color: "var(--text-primary)" }}>
                  {config.videos_per_month}
                </p>
                <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  Videos per month
                </p>
              </div>
              <div className="rounded-xl p-3"
                style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)" }}>
                <p className="text-2xl font-semibold font-body" style={{ color: "var(--text-primary)" }}>
                  {config.production_interval_days}
                </p>
                <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  Days between videos
                </p>
              </div>
            </div>
          </div>

          <div className="mt-5">
            <div className="flex items-center justify-between text-[11px] mb-1.5">
              <span style={{ color: "var(--text-secondary)" }}>This month progress</span>
              <span className="font-mono font-medium" style={{ color: "var(--turquoise)" }}>
                {state.videos_produced % config.videos_per_month} / {config.videos_per_month}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
              <motion.div
                className="h-full rounded-full"
                style={{ background: "var(--turquoise)" }}
                initial={{ width: 0 }}
                animate={{ width: `${cadenceProgress}%` }}
                transition={{ duration: 1, ease: "easeOut" as const }}
              />
            </div>
          </div>
        </GlassCard>
      </motion.div>

      {/* Decision Thresholds */}
      <motion.div variants={item}>
        <GlassCard>
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp size={16} style={{ color: "var(--turquoise)" }} />
            <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Decision Thresholds
            </h2>
          </div>
          <p className="text-[11px] mb-5" style={{ color: "var(--text-secondary)" }}>
            Rules that determine when to produce videos and how to evaluate performance
          </p>

          <div className="grid grid-cols-2 gap-3">
            {[
              { value: thresholds.min_confidence_score || 60, label: "Min confidence to launch", color: "var(--turquoise)" },
              { value: thresholds.min_competitor_vph || 50, label: "Min VPH to consider", color: "var(--gold)" },
              { value: `${thresholds.ctr_success_threshold || 4.0}%`, label: "CTR = Success", color: "var(--green)" },
              { value: `${thresholds.ctr_failure_threshold || 2.5}%`, label: "CTR = Needs work", color: "var(--red)" },
            ].map((t, i) => (
              <div
                key={i}
                className="rounded-xl p-4 relative overflow-hidden"
                style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)" }}
              >
                <div className="absolute top-0 left-0 w-8 h-0.5 rounded-full" style={{ background: t.color }} />
                <p className="text-xl font-semibold font-body" style={{ color: "var(--text-primary)" }}>
                  {t.value}
                </p>
                <p className="text-[11px] mt-0.5" style={{ color: "var(--text-secondary)" }}>
                  {t.label}
                </p>
              </div>
            ))}
          </div>
        </GlassCard>
      </motion.div>
    </motion.div>
  );
}
