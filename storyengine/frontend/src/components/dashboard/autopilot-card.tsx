"use client";

import { motion } from "framer-motion";
import { Brain, ChevronRight, Zap, Clock } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export interface AutopilotStatus {
  enabled: boolean;
  nextRecommendation: {
    title: string;
    confidence: number;
    reasoning: string[];
    modeledFrom?: string;
  } | null;
  daysUntilNext: number | null;
  videosProduced: number;
  channelAvgCtr: number;
}

interface AutopilotCardProps {
  status: AutopilotStatus;
  onLaunch?: () => void;
}

export function AutopilotCard({ status, onLaunch }: AutopilotCardProps) {
  const { enabled, nextRecommendation, daysUntilNext } = status;

  // Not enabled state
  if (!enabled) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--surface-elevated)]">
            <Brain size={20} className="text-[var(--text-secondary)]" />
          </div>
          <div className="flex-1">
            <p className="text-sm font-medium text-[var(--text-secondary)]">
              Autopilot is OFF
            </p>
            <p className="text-xs text-[var(--text-secondary)]">
              Enable autopilot to get AI-powered recommendations
            </p>
          </div>
          <Link
            href="/settings"
            className="rounded-lg bg-[var(--surface-elevated)] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            Enable
          </Link>
        </div>
      </div>
    );
  }

  // Ready with recommendation
  if (nextRecommendation) {
    return (
      <div className="overflow-hidden rounded-xl border border-[var(--accent)]/30 bg-gradient-to-br from-[var(--accent)]/5 to-transparent">
        <div className="p-4">
          <div className="flex items-start gap-3">
            {/* Pulsing indicator */}
            <div className="relative flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--accent)]/10">
              <motion.div
                animate={{ scale: [1, 1.15, 1], opacity: [1, 0.7, 1] }}
                transition={{ repeat: Infinity, duration: 2, ease: "easeInOut" }}
                className="absolute inset-0 rounded-lg bg-[var(--accent)]/20"
              />
              <Brain size={20} className="relative text-[var(--accent)]" />
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-[var(--accent)]">
                  Autopilot
                </span>
                <motion.span
                  animate={{ opacity: [1, 0.5, 1] }}
                  transition={{ repeat: Infinity, duration: 2 }}
                  className="flex h-2 w-2 rounded-full bg-green-500"
                />
              </div>
              <p className="mt-1 line-clamp-2 text-sm font-medium">
                {nextRecommendation.title}
              </p>
            </div>
          </div>

          {/* Confidence bar */}
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs">
              <span className="text-[var(--text-secondary)]">Confidence</span>
              <span className="font-medium text-[var(--accent)]">
                {nextRecommendation.confidence}%
              </span>
            </div>
            <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[var(--surface-elevated)]">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${nextRecommendation.confidence}%` }}
                transition={{ duration: 0.8, ease: "easeOut" as const }}
                className={cn(
                  "h-full rounded-full",
                  nextRecommendation.confidence >= 70
                    ? "bg-green-500"
                    : nextRecommendation.confidence >= 50
                    ? "bg-[var(--accent)]"
                    : "bg-[var(--warning)]"
                )}
              />
            </div>
          </div>

          {/* Modeled from */}
          {nextRecommendation.modeledFrom && (
            <p className="mt-3 text-xs text-[var(--text-secondary)]">
              Modeling: {nextRecommendation.modeledFrom}
            </p>
          )}

          {/* Actions */}
          <div className="mt-4 flex gap-2">
            <button
              onClick={onLaunch}
              className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-[var(--accent)] py-2.5 text-sm font-medium text-black transition-opacity hover:opacity-90"
            >
              <Zap size={16} />
              Launch Now
            </button>
            <Link
              href="/autopilot"
              className="flex items-center gap-1 rounded-lg bg-[var(--surface-elevated)] px-4 py-2.5 text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            >
              See Why
              <ChevronRight size={14} />
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Waiting state (no recommendation ready)
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--surface-elevated)]">
          <Clock size={20} className="text-[var(--text-secondary)]" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
              Autopilot
            </span>
            <span className="flex h-2 w-2 rounded-full bg-green-500" />
          </div>
          <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
            {daysUntilNext
              ? `Next production in ${daysUntilNext} day${daysUntilNext > 1 ? "s" : ""}`
              : "Analyzing candidates..."}
          </p>
        </div>
        <Link
          href="/autopilot"
          className="flex items-center gap-1 text-xs font-medium text-[var(--accent)]"
        >
          Details
          <ChevronRight size={14} />
        </Link>
      </div>
    </div>
  );
}
