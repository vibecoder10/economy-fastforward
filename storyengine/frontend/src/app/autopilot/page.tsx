"use client";

import { useState } from "react";
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
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

// Mock data - will be replaced with real API calls
const mockAutopilotState = {
  enabled: true,
  lastCycle: "2026-03-21T09:00:00Z",
  videosProduced: 26,
  channelAvgCtr: 4.2,
  nextProductionDate: "2026-03-25",
  daysUntilNext: 2,
};

const mockConfig = {
  videosPerMonth: 15,
  productionIntervalDays: 2,
  weights: {
    competitor_vph: 0.30,
    topic_channel_fit: 0.25,
    timing_freshness: 0.20,
    channel_momentum: 0.10,
    retention_patterns: 0.08,
    title_formula: 0.07,
  },
  thresholds: {
    min_confidence_score: 60,
    min_competitor_vph: 50,
    max_idea_age_days: 7,
    ctr_success_threshold: 4.0,
    ctr_failure_threshold: 2.5,
  },
};

const mockCandidates = [
  {
    id: "1",
    title: "China's $3T Dollar Trap",
    source: "CaspianReport",
    vph: 185,
    hoursOld: 18,
    confidence: 82,
  },
  {
    id: "2",
    title: "Why NATO's Next Move Changes Everything",
    source: "RealLifeLore",
    vph: 142,
    hoursOld: 36,
    confidence: 71,
  },
  {
    id: "3",
    title: "The Hidden Cost of Electric Cars",
    source: "Wendover",
    vph: 98,
    hoursOld: 48,
    confidence: 58,
  },
];

const mockLearnings = [
  { pattern: "Question format titles", effect: "+18% CTR", samples: 8 },
  { pattern: "Red/yellow thumbnails", effect: "+12% CTR", samples: 12 },
  { pattern: "Geopolitics + Finance combo", effect: "+22% retention", samples: 5 },
];

export default function AutopilotPage() {
  const [isEnabled, setIsEnabled] = useState(mockAutopilotState.enabled);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Autopilot</h1>
        <button
          onClick={() => setIsEnabled(!isEnabled)}
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
                ? `Next production slot in ${mockAutopilotState.daysUntilNext} days (${mockAutopilotState.nextProductionDate})`
                : "Enable autopilot to let AI manage video production"}
            </p>
          </div>
        </div>

        {/* Stats */}
        <div className="mt-5 grid grid-cols-3 gap-4 border-t border-[var(--border)] pt-5">
          <div>
            <p className="text-2xl font-bold">{mockAutopilotState.videosProduced}</p>
            <p className="text-xs text-[var(--text-secondary)]">Videos Produced</p>
          </div>
          <div>
            <p className="text-2xl font-bold">{mockAutopilotState.channelAvgCtr}%</p>
            <p className="text-xs text-[var(--text-secondary)]">Avg CTR</p>
          </div>
          <div>
            <p className="text-2xl font-bold">{mockConfig.videosPerMonth}</p>
            <p className="text-xs text-[var(--text-secondary)]">Target/Month</p>
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

        <div className="mt-4 space-y-3">
          {mockCandidates.map((candidate, i) => (
            <div
              key={candidate.id}
              className={cn(
                "flex items-center gap-3 rounded-lg p-3",
                i === 0
                  ? "border border-[var(--accent)]/30 bg-[var(--accent)]/5"
                  : "bg-[var(--surface-elevated)]"
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
                  {candidate.source} · VPH {candidate.vph} · {candidate.hoursOld}h old
                </p>
              </div>
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
                  {candidate.confidence}%
                </p>
                <p className="text-xs text-[var(--text-secondary)]">confidence</p>
              </div>
            </div>
          ))}
        </div>

        {mockCandidates.length > 0 && mockCandidates[0].confidence >= mockConfig.thresholds.min_confidence_score && (
          <button className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-[var(--accent)] py-2.5 text-sm font-medium text-black transition-opacity hover:opacity-90">
            <Zap size={16} />
            Launch Top Candidate Now
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
          How candidates are scored
        </p>

        <div className="mt-4 space-y-3">
          {Object.entries(mockConfig.weights).map(([key, value]) => (
            <div key={key}>
              <div className="flex items-center justify-between text-xs">
                <span className="text-[var(--text-secondary)]">
                  {key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                </span>
                <span className="font-medium">{(value * 100).toFixed(0)}%</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--surface-elevated)]">
                <div
                  className="h-full rounded-full bg-[var(--accent)]"
                  style={{ width: `${value * 100}%` }}
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
          Patterns discovered from video performance
        </p>

        <div className="mt-4 space-y-2">
          {mockLearnings.map((learning, i) => (
            <div
              key={i}
              className="flex items-center justify-between rounded-lg bg-[var(--surface-elevated)] px-3 py-2"
            >
              <span className="text-sm">{learning.pattern}</span>
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-green-500">{learning.effect}</span>
                <span className="text-xs text-[var(--text-secondary)]">n={learning.samples}</span>
              </div>
            </div>
          ))}
        </div>

        <Link
          href="/autopilot/learnings"
          className="mt-4 flex items-center justify-center gap-1 text-xs font-medium text-[var(--accent)]"
        >
          View All Learnings
          <ChevronRight size={14} />
        </Link>
      </div>

      {/* Cadence */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Calendar size={16} className="text-[var(--accent)]" />
          Production Cadence
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4">
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
            <p className="text-2xl font-bold">{mockConfig.videosPerMonth}</p>
            <p className="text-xs text-[var(--text-secondary)]">Videos per month</p>
          </div>
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
            <p className="text-2xl font-bold">{mockConfig.productionIntervalDays}</p>
            <p className="text-xs text-[var(--text-secondary)]">Days between videos</p>
          </div>
        </div>

        <div className="mt-4">
          <div className="flex items-center justify-between text-xs">
            <span className="text-[var(--text-secondary)]">This month progress</span>
            <span className="font-medium">12 / {mockConfig.videosPerMonth}</span>
          </div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[var(--surface-elevated)]">
            <div
              className="h-full rounded-full bg-[var(--accent)]"
              style={{ width: `${(12 / mockConfig.videosPerMonth) * 100}%` }}
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

        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
            <p className="text-lg font-bold">{mockConfig.thresholds.min_confidence_score}</p>
            <p className="text-xs text-[var(--text-secondary)]">Min confidence</p>
          </div>
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
            <p className="text-lg font-bold">{mockConfig.thresholds.min_competitor_vph}</p>
            <p className="text-xs text-[var(--text-secondary)]">Min VPH</p>
          </div>
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
            <p className="text-lg font-bold">{mockConfig.thresholds.ctr_success_threshold}%</p>
            <p className="text-xs text-[var(--text-secondary)]">CTR success</p>
          </div>
          <div className="rounded-lg bg-[var(--surface-elevated)] p-3">
            <p className="text-lg font-bold">{mockConfig.thresholds.ctr_failure_threshold}%</p>
            <p className="text-xs text-[var(--text-secondary)]">CTR failure</p>
          </div>
        </div>
      </div>
    </div>
  );
}
