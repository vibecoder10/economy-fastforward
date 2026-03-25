"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Power,
  Calendar,
  TrendingUp,
  Clock,
  BarChart3,
  Lightbulb,
  ChevronRight,
  Check,
  X,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import {
  getAutopilotSummary,
  toggleAutopilot,
  updateAutopilotConfig,
  launchCandidate,
  getAgentStats,
  getNicheConfig,
  AutopilotSummary,
  CompetitorCandidate,
} from "@/lib/api";
import { NicheSetup } from "@/components/autopilot/niche-setup";
import { PlayingCard } from "@/components/autopilot/playing-card";
import { CardExpanded } from "@/components/autopilot/card-expanded";

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

export default function AutopilotPage() {
  const [data, setData] = useState<AutopilotSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isEnabled, setIsEnabled] = useState(true);
  const [editingTarget, setEditingTarget] = useState(false);
  const [targetValue, setTargetValue] = useState(15);
  const [savingTarget, setSavingTarget] = useState(false);
  const [selectedCandidate, setSelectedCandidate] = useState<CompetitorCandidate | null>(null);
  const [nicheConfigured, setNicheConfigured] = useState(true);

  const { data: agentStats } = useQuery({
    queryKey: ["agent-stats"],
    queryFn: getAgentStats,
  });

  const { data: nicheConfig } = useQuery({
    queryKey: ["niche-config"],
    queryFn: getNicheConfig,
  });

  useEffect(() => {
    if (nicheConfig && !nicheConfig.niche_category) {
      setNicheConfigured(false);
    } else if (nicheConfig) {
      setNicheConfigured(true);
    }
  }, [nicheConfig]);

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

  if (!nicheConfigured) {
    return <NicheSetup onComplete={() => setNicheConfigured(true)} />;
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">Autopilot</h1>
        </div>
        <div className="animate-pulse space-y-4">
          <div className="h-40 rounded-xl bg-[var(--bg-card)]" />
          <div className="h-60 rounded-xl bg-[var(--bg-card)]" />
          <div className="h-40 rounded-xl bg-[var(--bg-card)]" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">Autopilot</h1>
        </div>
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-5 text-red-400">
          {error || "Failed to load data"}
        </div>
      </div>
    );
  }

  const { state, config, learnings } = data;
  const weights = Object.keys(config.weights).length > 0 ? config.weights : DEFAULT_WEIGHTS;
  const thresholds = Object.keys(config.thresholds).length > 0 ? config.thresholds : DEFAULT_THRESHOLDS;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Autopilot</h1>
        <button
          onClick={handleToggle}
          className={cn(
            "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
            isEnabled
              ? "bg-green-500/10 text-green-500"
              : "bg-[var(--bg-card)] text-[var(--text-secondary)]"
          )}
        >
          <Power size={16} />
          {isEnabled ? "ON" : "OFF"}
        </button>
      </div>

      {/* Status Card */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-5">
        <div className="flex items-start gap-4">
          <div className="relative flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--amber)]/10">
            {isEnabled && (
              <motion.div
                animate={{ scale: [1, 1.2, 1], opacity: [1, 0.5, 1] }}
                transition={{ repeat: Infinity, duration: 2 }}
                className="absolute inset-0 rounded-xl bg-[var(--amber)]/20"
              />
            )}
            <Brain size={24} className={isEnabled ? "text-[var(--amber)]" : "text-[var(--text-secondary)]"} />
          </div>
          <div className="flex-1">
            <h2 className="font-semibold">
              {isEnabled ? "Autopilot Active" : "Autopilot Disabled"}
            </h2>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              {isEnabled
                ? `Next production slot in ${state.days_until_next} days (${state.next_production_date})`
                : "Enable autopilot to let AI manage video production"}
            </p>
          </div>
        </div>

        {/* Stats */}
        <div className="mt-5 grid grid-cols-3 gap-4 border-t border-[var(--border)] pt-5">
          <div>
            <p className="text-2xl font-bold">{state.videos_produced}</p>
            <p className="text-xs text-[var(--text-secondary)]">Videos Produced</p>
          </div>
          <div>
            <p className="text-2xl font-bold">{state.channel_avg_ctr}%</p>
            <p className="text-xs text-[var(--text-secondary)]">Avg CTR</p>
          </div>
          <div>
            {editingTarget ? (
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={targetValue}
                  onChange={(e) => setTargetValue(parseInt(e.target.value) || 1)}
                  min={1}
                  max={30}
                  className="w-16 rounded-md bg-[var(--bg-card-hover)] px-2 py-1 text-lg font-bold focus:outline-none focus:ring-1 focus:ring-[var(--amber)]"
                  autoFocus
                />
                <button
                  onClick={handleSaveTarget}
                  disabled={savingTarget}
                  className="rounded-md p-1 text-green-500 hover:bg-green-500/10"
                >
                  <Check size={16} />
                </button>
                <button
                  onClick={() => {
                    setEditingTarget(false);
                    setTargetValue(config.videos_per_month);
                  }}
                  className="rounded-md p-1 text-red-500 hover:bg-red-500/10"
                >
                  <X size={16} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setEditingTarget(true)}
                className="group text-left"
              >
                <p className="text-2xl font-bold group-hover:text-[var(--amber)]">
                  {config.videos_per_month}
                </p>
                <p className="text-xs text-[var(--text-secondary)] group-hover:text-[var(--amber)]">
                  Target/Month (click to edit)
                </p>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Script Quality */}
      {agentStats && agentStats.total_scripts > 0 && (
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <h2
            className="text-sm font-semibold uppercase tracking-wider mb-4"
            style={{ color: "var(--text-muted)" }}
          >
            Script Quality
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>Avg Hook Score</span>
              <p className="text-xl font-bold" style={{ color: agentStats.avg_hook_score >= 70 ? "var(--green)" : "var(--amber)" }}>
                {agentStats.avg_hook_score.toFixed(0)}
              </p>
            </div>
            <div>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>Avg Body Score</span>
              <p className="text-xl font-bold" style={{ color: agentStats.avg_body_score >= 70 ? "var(--green)" : "var(--amber)" }}>
                {agentStats.avg_body_score.toFixed(0)}
              </p>
            </div>
            <div>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>Scripts Processed</span>
              <p className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
                {agentStats.total_scripts}
              </p>
            </div>
            <div>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>Total Cost</span>
              <p className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
                ${agentStats.total_cost.toFixed(2)}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Topic Discovery — Playing Cards */}
      {data?.candidates && data.candidates.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider mb-4"
              style={{ color: "var(--text-muted)" }}>
            Topic Discovery
            {nicheConfig?.sub_niche && (
              <span style={{ color: "var(--text-secondary)" }}> · {nicheConfig.sub_niche}</span>
            )}
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.candidates.map((candidate: CompetitorCandidate) => (
              <PlayingCard
                key={candidate.id}
                candidate={candidate}
                onModel={setSelectedCandidate}
              />
            ))}
          </div>
        </div>
      )}

      {/* Expanded card modal */}
      <AnimatePresence>
        {selectedCandidate && (
          <CardExpanded
            candidate={selectedCandidate}
            onClose={() => setSelectedCandidate(null)}
            onProduce={async (candidate, thumbnailVersion) => {
              try {
                await launchCandidate(candidate.id);
                setSelectedCandidate(null);
                const summary = await getAutopilotSummary();
                setData(summary);
              } catch (err) {
                console.error("Failed to launch:", err);
              }
            }}
          />
        )}
      </AnimatePresence>

      {/* Configuration */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <BarChart3 size={16} className="text-[var(--amber)]" />
          Confidence Weights
        </div>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          How candidates are scored — VPH measures viral potential, Freshness measures topic timeliness
        </p>

        <div className="mt-4 space-y-3">
          {Object.entries(weights).map(([key, value]) => (
            <div key={key}>
              <div className="flex items-center justify-between text-xs">
                <span className="text-[var(--text-secondary)]">
                  {key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                </span>
                <span className="font-medium">{(Number(value) * 100).toFixed(0)}%</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--bg-card-hover)]">
                <div
                  className="h-full rounded-full bg-[var(--amber)]"
                  style={{ width: `${Number(value) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Learnings */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Lightbulb size={16} className="text-[var(--amber)]" />
          Learned Patterns
        </div>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Patterns discovered from video performance — used to guide future decisions
        </p>

        {learnings.length === 0 ? (
          <div className="mt-4 rounded-lg bg-[var(--bg-card-hover)] p-4 text-center text-sm text-[var(--text-secondary)]">
            No learnings yet. Patterns will be extracted after videos are published.
          </div>
        ) : (
          <div className="mt-4 space-y-2">
            {learnings.map((learning) => (
              <div
                key={learning.id}
                className="flex items-center justify-between rounded-lg bg-[var(--bg-card-hover)] px-3 py-2"
              >
                <div className="flex-1 min-w-0">
                  <span className="text-sm truncate block">{learning.pattern}</span>
                  <span className="text-xs text-[var(--text-secondary)]">
                    {learning.category} · {Math.round(learning.confidence)}% confidence
                  </span>
                </div>
                <div className="flex items-center gap-3 ml-2">
                  {learning.effect && (
                    <span className="text-sm font-medium text-green-500">{learning.effect}</span>
                  )}
                  <span className="text-xs text-[var(--text-secondary)]">n={learning.sample_size}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {learnings.length > 0 && (
          <Link
            href="/autopilot/learnings"
            className="mt-4 flex items-center justify-center gap-1 text-xs font-medium text-[var(--amber)]"
          >
            View All Learnings
            <ChevronRight size={14} />
          </Link>
        )}
      </div>

      {/* Cadence */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Calendar size={16} className="text-[var(--amber)]" />
          Production Cadence
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4">
          <div className="rounded-lg bg-[var(--bg-card-hover)] p-3">
            <p className="text-2xl font-bold">{config.videos_per_month}</p>
            <p className="text-xs text-[var(--text-secondary)]">Videos per month</p>
          </div>
          <div className="rounded-lg bg-[var(--bg-card-hover)] p-3">
            <p className="text-2xl font-bold">{config.production_interval_days}</p>
            <p className="text-xs text-[var(--text-secondary)]">Days between videos</p>
          </div>
        </div>

        <div className="mt-4">
          <div className="flex items-center justify-between text-xs">
            <span className="text-[var(--text-secondary)]">This month progress</span>
            <span className="font-medium">
              {state.videos_produced % config.videos_per_month} / {config.videos_per_month}
            </span>
          </div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[var(--bg-card-hover)]">
            <div
              className="h-full rounded-full bg-[var(--amber)]"
              style={{ width: `${((state.videos_produced % config.videos_per_month) / config.videos_per_month) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Thresholds */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <TrendingUp size={16} className="text-[var(--amber)]" />
          Decision Thresholds
        </div>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Rules that determine when to produce videos and how to evaluate performance
        </p>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-[var(--bg-card-hover)] p-3">
            <p className="text-lg font-bold">{thresholds.min_confidence_score || 60}</p>
            <p className="text-xs text-[var(--text-secondary)]">Min confidence to launch</p>
          </div>
          <div className="rounded-lg bg-[var(--bg-card-hover)] p-3">
            <p className="text-lg font-bold">{thresholds.min_competitor_vph || 50}</p>
            <p className="text-xs text-[var(--text-secondary)]">Min VPH to consider</p>
          </div>
          <div className="rounded-lg bg-[var(--bg-card-hover)] p-3">
            <p className="text-lg font-bold">{thresholds.ctr_success_threshold || 4.0}%</p>
            <p className="text-xs text-[var(--text-secondary)]">CTR = Success</p>
          </div>
          <div className="rounded-lg bg-[var(--bg-card-hover)] p-3">
            <p className="text-lg font-bold">{thresholds.ctr_failure_threshold || 2.5}%</p>
            <p className="text-xs text-[var(--text-secondary)]">CTR = Needs work</p>
          </div>
        </div>
      </div>

      {/* Niche Settings */}
      {nicheConfig && nicheConfig.niche_category && (
        <div className="rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
          <h2 className="text-sm font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>
            Niche Settings
          </h2>
          <div className="space-y-1 text-sm" style={{ color: "var(--text-secondary)" }}>
            <p>Category: <span style={{ color: "var(--text-primary)" }}>{nicheConfig.niche_category}</span></p>
            <p>Sub-niche: <span style={{ color: "var(--text-primary)" }}>{nicheConfig.sub_niche}</span></p>
          </div>
        </div>
      )}
    </div>
  );
}
