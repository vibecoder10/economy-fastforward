"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Brain,
  Power,
  Calendar,
  Target,
  TrendingUp,
  Clock,
  Zap,
  BarChart3,
  Lightbulb,
  ChevronRight,
  ChevronDown,
  Info,
  ExternalLink,
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
} from "@/lib/api";

// Types matching the API response
interface ConfidenceBreakdown {
  vph_score: number;
  vph_reasoning: string;
  freshness_score: number;
  freshness_reasoning: string;
  total_score: number;
}

interface Candidate {
  id: string;
  title: string;
  source: string;
  url: string | null;
  vph: number;
  hours_old: number;
  confidence: number;
  confidence_breakdown?: ConfidenceBreakdown;
  published_date: string | null;
  modeled: boolean;
}

interface Learning {
  id: string;
  pattern: string;
  category: string;
  effect: string;
  confidence: number;
  sample_size: number;
  avg_ctr?: number;
}

interface AutopilotState {
  enabled: boolean;
  last_cycle: string | null;
  videos_produced: number;
  channel_avg_ctr: number;
  next_production_date: string | null;
  days_until_next: number;
}

interface AutopilotConfig {
  videos_per_month: number;
  production_interval_days: number;
  weights: Record<string, number>;
  thresholds: Record<string, number>;
}

interface AutopilotSummary {
  state: AutopilotState;
  config: AutopilotConfig;
  candidates: Candidate[];
  learnings: Learning[];
}

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
  const [expandedCandidate, setExpandedCandidate] = useState<string | null>(null);
  const [editingTarget, setEditingTarget] = useState(false);
  const [targetValue, setTargetValue] = useState(15);
  const [savingTarget, setSavingTarget] = useState(false);
  const [launchingId, setLaunchingId] = useState<string | null>(null);

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

  const handleLaunch = async (candidateId: string) => {
    setLaunchingId(candidateId);
    try {
      await launchCandidate(candidateId);
      // Refresh data
      const summary = await getAutopilotSummary();
      setData(summary);
    } catch (err) {
      console.error("Error launching candidate:", err);
    } finally {
      setLaunchingId(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">Autopilot</h1>
        </div>
        <div className="animate-pulse space-y-4">
          <div className="h-40 rounded-xl bg-[var(--surface)]" />
          <div className="h-60 rounded-xl bg-[var(--surface)]" />
          <div className="h-40 rounded-xl bg-[var(--surface)]" />
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

  const { state, config, candidates, learnings } = data;
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
              : "bg-[var(--surface)] text-[var(--text-secondary)]"
          )}
        >
          <Power size={16} />
          {isEnabled ? "ON" : "OFF"}
        </button>
      </div>

      {/* Status Card */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <div className="flex items-start gap-4">
          <div className="relative flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--accent)]/10">
            {isEnabled && (
              <motion.div
                animate={{ scale: [1, 1.2, 1], opacity: [1, 0.5, 1] }}
                transition={{ repeat: Infinity, duration: 2 }}
                className="absolute inset-0 rounded-xl bg-[var(--accent)]/20"
              />
            )}
            <Brain size={24} className={isEnabled ? "text-[var(--accent)]" : "text-[var(--text-secondary)]"} />
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
                  className="w-16 rounded-md bg-[var(--surface-elevated)] px-2 py-1 text-lg font-bold focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
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
                <p className="text-2xl font-bold group-hover:text-[var(--accent)]">
                  {config.videos_per_month}
                </p>
                <p className="text-xs text-[var(--text-secondary)] group-hover:text-[var(--accent)]">
                  Target/Month (click to edit)
                </p>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Candidates Section */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Target size={16} className="text-[var(--accent)]" />
          Top Candidates
        </div>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Ideas being evaluated for next production slot
        </p>

        {candidates.length === 0 ? (
          <div className="mt-4 rounded-lg bg-[var(--surface-elevated)] p-4 text-center text-sm text-[var(--text-secondary)]">
            No candidates found. Waiting for competitor videos to be scraped.
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {candidates.map((candidate, i) => (
              <div key={candidate.id}>
                <button
                  onClick={() => setExpandedCandidate(
                    expandedCandidate === candidate.id ? null : candidate.id
                  )}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg p-3 text-left transition-colors",
                    i === 0
                      ? "border border-[var(--accent)]/30 bg-[var(--accent)]/5"
                      : "bg-[var(--surface-elevated)] hover:bg-[var(--surface-elevated)]/80"
                  )}
                >
                  <div
                    className={cn(
                      "flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold",
                      i === 0
                        ? "bg-[var(--accent)] text-black"
                        : "bg-[var(--border)] text-[var(--text-secondary)]"
                    )}
                  >
                    {i + 1}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{candidate.title}</p>
                    <p className="text-xs text-[var(--text-secondary)]">
                      {candidate.source} · VPH {candidate.vph.toLocaleString()} · {Math.round(candidate.hours_old)}h old
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="text-right">
                      <p
                        className={cn(
                          "text-sm font-bold",
                          candidate.confidence >= 70
                            ? "text-green-500"
                            : candidate.confidence >= 50
                            ? "text-[var(--accent)]"
                            : "text-[var(--text-secondary)]"
                        )}
                      >
                        {Math.round(candidate.confidence)}%
                      </p>
                      <p className="text-xs text-[var(--text-secondary)]">confidence</p>
                    </div>
                    <ChevronDown
                      size={16}
                      className={cn(
                        "text-[var(--text-secondary)] transition-transform",
                        expandedCandidate === candidate.id && "rotate-180"
                      )}
                    />
                  </div>
                </button>

                {/* Expanded Confidence Breakdown */}
                {expandedCandidate === candidate.id && candidate.confidence_breakdown && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="mt-2 overflow-hidden rounded-lg bg-[var(--surface-elevated)] p-4"
                  >
                    <div className="flex items-center gap-2 text-xs font-semibold text-[var(--text-secondary)] mb-3">
                      <Info size={14} />
                      Why this score?
                    </div>

                    <div className="space-y-3">
                      {/* VPH Score */}
                      <div>
                        <div className="flex items-center justify-between text-xs mb-1">
                          <span className="text-[var(--text-secondary)]">
                            VPH Score (55% weight)
                          </span>
                          <span className="font-medium">
                            {Math.round(candidate.confidence_breakdown.vph_score)}/100
                          </span>
                        </div>
                        <div className="h-2 rounded-full bg-[var(--border)] overflow-hidden">
                          <div
                            className="h-full bg-[var(--accent)] rounded-full transition-all"
                            style={{ width: `${candidate.confidence_breakdown.vph_score}%` }}
                          />
                        </div>
                        <p className="text-xs text-[var(--text-secondary)] mt-1">
                          {candidate.confidence_breakdown.vph_reasoning}
                        </p>
                      </div>

                      {/* Freshness Score */}
                      <div>
                        <div className="flex items-center justify-between text-xs mb-1">
                          <span className="text-[var(--text-secondary)]">
                            Freshness Score (45% weight)
                          </span>
                          <span className="font-medium">
                            {Math.round(candidate.confidence_breakdown.freshness_score)}/100
                          </span>
                        </div>
                        <div className="h-2 rounded-full bg-[var(--border)] overflow-hidden">
                          <div
                            className="h-full bg-green-500 rounded-full transition-all"
                            style={{ width: `${candidate.confidence_breakdown.freshness_score}%` }}
                          />
                        </div>
                        <p className="text-xs text-[var(--text-secondary)] mt-1">
                          {candidate.confidence_breakdown.freshness_reasoning}
                        </p>
                      </div>

                      {/* Total */}
                      <div className="pt-2 border-t border-[var(--border)]">
                        <div className="flex items-center justify-between text-sm">
                          <span className="font-medium">Total Confidence</span>
                          <span className={cn(
                            "font-bold",
                            candidate.confidence >= 70
                              ? "text-green-500"
                              : candidate.confidence >= 50
                              ? "text-[var(--accent)]"
                              : "text-[var(--text-secondary)]"
                          )}>
                            {Math.round(candidate.confidence_breakdown.total_score)}%
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2 mt-4 pt-3 border-t border-[var(--border)]">
                      {candidate.url && (
                        <a
                          href={candidate.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium bg-[var(--border)] hover:bg-[var(--border)]/80 transition-colors"
                        >
                          <ExternalLink size={12} />
                          Watch Video
                        </a>
                      )}
                      <button
                        onClick={() => handleLaunch(candidate.id)}
                        disabled={launchingId === candidate.id}
                        className={cn(
                          "flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                          "bg-[var(--accent)] text-black hover:opacity-90",
                          launchingId === candidate.id && "opacity-50 cursor-not-allowed"
                        )}
                      >
                        <Zap size={12} />
                        {launchingId === candidate.id ? "Launching..." : "Launch This"}
                      </button>
                    </div>
                  </motion.div>
                )}
              </div>
            ))}
          </div>
        )}

        {candidates.length > 0 && candidates[0].confidence >= (thresholds.min_confidence_score || 60) && (
          <button
            onClick={() => handleLaunch(candidates[0].id)}
            disabled={launchingId === candidates[0].id}
            className={cn(
              "mt-4 flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-medium transition-opacity",
              "bg-[var(--accent)] text-black hover:opacity-90",
              launchingId === candidates[0].id && "opacity-50 cursor-not-allowed"
            )}
          >
            <Zap size={16} />
            {launchingId === candidates[0].id ? "Launching..." : "Launch Top Candidate Now"}
          </button>
        )}
      </div>

      {/* Configuration */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <BarChart3 size={16} className="text-[var(--accent)]" />
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
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--surface-elevated)]">
                <div
                  className="h-full rounded-full bg-[var(--accent)]"
                  style={{ width: `${Number(value) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Learnings */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Lightbulb size={16} className="text-[var(--accent)]" />
          Learned Patterns
        </div>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Patterns discovered from video performance — used to guide future decisions
        </p>

        {learnings.length === 0 ? (
          <div className="mt-4 rounded-lg bg-[var(--surface-elevated)] p-4 text-center text-sm text-[var(--text-secondary)]">
            No learnings yet. Patterns will be extracted after videos are published.
          </div>
        ) : (
          <div className="mt-4 space-y-2">
            {learnings.map((learning) => (
              <div
                key={learning.id}
                className="flex items-center justify-between rounded-lg bg-[var(--surface-elevated)] px-3 py-2"
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
            className="mt-4 flex items-center justify-center gap-1 text-xs font-medium text-[var(--accent)]"
          >
            View All Learnings
            <ChevronRight size={14} />
          </Link>
        )}
      </div>

      {/* Cadence */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Calendar size={16} className="text-[var(--accent)]" />
          Production Cadence
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4">
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
            <p className="text-2xl font-bold">{config.videos_per_month}</p>
            <p className="text-xs text-[var(--text-secondary)]">Videos per month</p>
          </div>
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
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
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[var(--surface-elevated)]">
            <div
              className="h-full rounded-full bg-[var(--accent)]"
              style={{ width: `${((state.videos_produced % config.videos_per_month) / config.videos_per_month) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Thresholds */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <TrendingUp size={16} className="text-[var(--accent)]" />
          Decision Thresholds
        </div>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Rules that determine when to produce videos and how to evaluate performance
        </p>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
            <p className="text-lg font-bold">{thresholds.min_confidence_score || 60}</p>
            <p className="text-xs text-[var(--text-secondary)]">Min confidence to launch</p>
          </div>
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
            <p className="text-lg font-bold">{thresholds.min_competitor_vph || 50}</p>
            <p className="text-xs text-[var(--text-secondary)]">Min VPH to consider</p>
          </div>
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
            <p className="text-lg font-bold">{thresholds.ctr_success_threshold || 4.0}%</p>
            <p className="text-xs text-[var(--text-secondary)]">CTR = Success</p>
          </div>
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
            <p className="text-lg font-bold">{thresholds.ctr_failure_threshold || 2.5}%</p>
            <p className="text-xs text-[var(--text-secondary)]">CTR = Needs work</p>
          </div>
        </div>
      </div>
    </div>
  );
}
