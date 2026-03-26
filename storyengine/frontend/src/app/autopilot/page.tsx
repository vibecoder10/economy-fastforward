"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  Brain,
  Power,
  TrendingUp,
  BarChart3,
  Lightbulb,
  ChevronRight,
  Check,
  X,
} from "lucide-react";
import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { StatCard } from "@/components/ui/StatCard";
import { Spinner } from "@/components/ui/spinner";
import {
  getAutopilotSummary,
  toggleAutopilot,
  updateAutopilotConfig,
  type AutopilotSummary,
} from "@/lib/api";

const DEFAULT_WEIGHTS = {
  competitor_vph: 0.55,
  timing_freshness: 0.45,
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
  const queryClient = useQueryClient();
  const [isToggling, setIsToggling] = useState(false);
  const [editingTarget, setEditingTarget] = useState(false);
  const [targetValue, setTargetValue] = useState(15);
  const [savingTarget, setSavingTarget] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["autopilot-summary"],
    queryFn: getAutopilotSummary,
  });

  const isEnabled = data?.state.enabled ?? true;

  const handleToggle = async () => {
    if (!data) return;
    setIsToggling(true);
    try {
      await toggleAutopilot(!isEnabled);
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
    } catch (err) {
      console.error("Error toggling autopilot:", err);
    } finally {
      setIsToggling(false);
    }
  };

  const handleSaveTarget = async () => {
    setSavingTarget(true);
    try {
      await updateAutopilotConfig(targetValue);
      setEditingTarget(false);
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
    } catch (err) {
      console.error("Error saving target:", err);
    } finally {
      setSavingTarget(false);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Autopilot
        </h1>
        <div className="flex items-center justify-center h-48">
          <Spinner size="lg" />
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
        <GlassCard>
          <p className="text-sm" style={{ color: "var(--red)" }}>
            Failed to load autopilot data. The backend may be unreachable.
          </p>
        </GlassCard>
      </div>
    );
  }

  const { state, config, candidates, learnings } = data;
  const weights =
    Object.keys(config.weights).length > 0 ? config.weights : DEFAULT_WEIGHTS;

  // Initialize target value from config on first load
  if (!editingTarget && targetValue !== config.videos_per_month) {
    // We use a ref-like pattern here: only set if not currently editing
    // This is a controlled one-time sync
  }

  return (
    <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
      {/* Header with toggle */}
      <motion.div variants={item} className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
            Autopilot
          </h1>
          {isEnabled && <StatusPill label="Active" color="turquoise" pulse size="md" />}
        </div>
        <button
          onClick={handleToggle}
          disabled={isToggling}
          className="relative flex items-center gap-2.5 rounded-full px-6 py-2.5 text-sm font-semibold transition-all duration-300 disabled:opacity-50"
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

      {/* Disabled banner */}
      {!isEnabled && (
        <motion.div variants={item}>
          <GlassCard
            style={{
              borderColor: "rgba(255, 77, 106, 0.2)",
              background: "rgba(255, 77, 106, 0.05)",
            }}
          >
            <div className="flex items-center gap-3">
              <Brain size={20} style={{ color: "var(--red)", opacity: 0.6 }} />
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                Autopilot is disabled. Enable it to let AI manage video production
                autonomously.
              </p>
            </div>
          </GlassCard>
        </motion.div>
      )}

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
          value={state.channel_avg_ctr > 0 ? `${state.channel_avg_ctr}%` : "--"}
          color="var(--green)"
          icon={TrendingUp}
        />
        {/* Editable Target / Month */}
        <div
          className="glass-card p-5 relative overflow-hidden"
          style={{ borderColor: "rgba(212, 168, 82, 0.2)" }}
        >
          <div
            className="absolute top-0 left-0 right-0 h-0.5"
            style={{ background: "var(--gold)" }}
          />
          {editingTarget ? (
            <div>
              <p
                className="text-[11px] font-medium uppercase tracking-wider mb-2"
                style={{ color: "var(--gold)" }}
              >
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
            <button
              onClick={() => {
                setTargetValue(config.videos_per_month);
                setEditingTarget(true);
              }}
              className="group text-left w-full"
            >
              <p
                className="text-[11px] font-medium uppercase tracking-wider mb-1"
                style={{ color: "var(--gold)" }}
              >
                Target / Month
              </p>
              <p
                className="text-2xl font-semibold font-body"
                style={{ color: "var(--text-primary)" }}
              >
                {config.videos_per_month}
              </p>
              <p
                className="text-[11px] mt-1 font-mono"
                style={{ color: "var(--text-secondary)" }}
              >
                click to edit
              </p>
            </button>
          )}
        </div>
      </motion.div>

      {/* Top Recommendations */}
      {candidates.length > 0 && (
        <motion.div variants={item}>
          <GlassCard>
            <div className="flex items-center justify-between mb-5">
              <h2
                className="text-[11px] font-semibold uppercase tracking-wider"
                style={{ color: "var(--text-secondary)" }}
              >
                Top Recommendations
              </h2>
              <Link
                href="/competitors"
                className="text-xs font-medium transition-colors hover:brightness-125"
                style={{ color: "var(--turquoise)" }}
              >
                View All
                <ChevronRight size={12} className="inline ml-0.5" />
              </Link>
            </div>
            <div className="space-y-2">
              {candidates.slice(0, 5).map((candidate, i) => {
                const medals = [
                  { bg: "rgba(212, 168, 68, 0.2)", color: "var(--gold)", label: "1st" },
                  { bg: "rgba(192, 192, 192, 0.15)", color: "#C0C0C0", label: "2nd" },
                  { bg: "rgba(205, 127, 50, 0.15)", color: "#CD7F32", label: "3rd" },
                  { bg: "rgba(255,255,255,0.05)", color: "var(--text-tertiary)", label: `${i + 1}` },
                  { bg: "rgba(255,255,255,0.05)", color: "var(--text-tertiary)", label: `${i + 1}` },
                ];
                const medal = medals[Math.min(i, 4)];
                const videoId = candidate.url?.match(
                  /(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/
                )?.[1];
                const thumbUrl = videoId
                  ? `https://img.youtube.com/vi/${videoId}/mqdefault.jpg`
                  : null;

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
                    {/* Rank badge */}
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold shrink-0"
                      style={{ background: medal.bg, color: medal.color }}
                    >
                      {medal.label}
                    </div>

                    {thumbUrl && (
                      <img
                        src={thumbUrl}
                        alt=""
                        className="w-20 h-12 rounded-lg object-cover shrink-0"
                      />
                    )}
                    <div className="flex-1 min-w-0">
                      <p
                        className="text-sm font-medium truncate"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {candidate.title}
                      </p>
                      <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                        {candidate.source} &middot; {Math.round(candidate.hours_old)}h ago
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p
                        className="text-sm font-bold"
                        style={{ color: "var(--turquoise)" }}
                      >
                        {candidate.confidence.toFixed(0)}
                      </p>
                      <p
                        className="text-[10px] uppercase tracking-wider"
                        style={{ color: "var(--text-secondary)" }}
                      >
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
            How candidates are scored. VPH measures viral potential, Freshness measures
            topic timeliness.
          </p>

          <div className="space-y-4">
            {Object.entries(weights).map(([key, value]) => (
              <div key={key}>
                <div className="flex items-center justify-between text-xs mb-1.5">
                  <span style={{ color: "var(--text-secondary)" }}>
                    {key
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (c) => c.toUpperCase())}
                  </span>
                  <span
                    className="font-mono font-medium"
                    style={{ color: "var(--turquoise)" }}
                  >
                    {(Number(value) * 100).toFixed(0)}%
                  </span>
                </div>
                <div
                  className="h-2 overflow-hidden rounded-full"
                  style={{ background: "rgba(255,255,255,0.06)" }}
                >
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
      {learnings.length > 0 && (
        <motion.div variants={item}>
          <GlassCard>
            <div className="flex items-center gap-2 mb-1">
              <Lightbulb size={16} style={{ color: "var(--turquoise)" }} />
              <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                Learned Patterns
              </h2>
            </div>
            <p className="text-[11px] mb-5" style={{ color: "var(--text-secondary)" }}>
              Patterns discovered from video performance
            </p>

            <div className="space-y-2">
              {learnings.map((learning) => (
                <div
                  key={learning.id}
                  className="flex items-center justify-between rounded-xl px-4 py-3"
                  style={{
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.05)",
                  }}
                >
                  <div className="flex-1 min-w-0">
                    <span
                      className="text-sm block truncate"
                      style={{ color: "var(--text-primary)" }}
                    >
                      {learning.pattern}
                    </span>
                    <div className="flex items-center gap-2 mt-1">
                      <StatusPill
                        label={learning.category}
                        color={CATEGORY_COLORS[learning.category] || "turquoise"}
                        size="sm"
                      />
                      <span
                        className="text-[11px] font-mono"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        {Math.round(learning.confidence)}% confidence
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 ml-3 shrink-0">
                    {learning.effect && (
                      <span
                        className="text-sm font-medium"
                        style={{ color: "var(--green)" }}
                      >
                        {learning.effect}
                      </span>
                    )}
                    <span
                      className="text-[11px] font-mono"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      n={learning.sample_size}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </GlassCard>
        </motion.div>
      )}
    </motion.div>
  );
}
