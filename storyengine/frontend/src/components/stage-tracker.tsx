"use client";

import { cn } from "@/lib/utils";
import { PIPELINE_STAGES, getStageIndex } from "@/lib/constants";
import { Check } from "lucide-react";

interface StageTrackerProps {
  status: string;
}

const DOT_COLORS: Record<string, string> = {
  slate: "border-slate-500 bg-slate-500",
  blue: "border-blue-500 bg-blue-500",
  cyan: "border-cyan-500 bg-cyan-500",
  amber: "border-amber-500 bg-amber-500",
  violet: "border-violet-500 bg-violet-500",
  orange: "border-orange-500 bg-orange-500",
  rose: "border-rose-500 bg-rose-500",
  emerald: "border-emerald-500 bg-emerald-500",
  green: "border-green-500 bg-green-500",
};

export function StageTracker({ status }: StageTrackerProps) {
  const currentIndex = getStageIndex(status);

  return (
    <div className="flex flex-col gap-0">
      {PIPELINE_STAGES.map((stage, i) => {
        const isDone = i < currentIndex;
        const isCurrent = i === currentIndex;

        return (
          <div key={stage.key} className="flex items-start gap-3">
            {/* Vertical line + dot */}
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  "flex h-6 w-6 items-center justify-center rounded-full border-2",
                  isDone && DOT_COLORS[stage.color],
                  isCurrent && `${DOT_COLORS[stage.color]} animate-pulse-dot`,
                  !isDone && !isCurrent && "border-white/10 bg-transparent"
                )}
              >
                {isDone && <Check size={12} className="text-white" />}
              </div>
              {i < PIPELINE_STAGES.length - 1 && (
                <div
                  className={cn(
                    "h-6 w-0.5",
                    isDone ? "bg-white/20" : "bg-white/5"
                  )}
                />
              )}
            </div>

            {/* Label */}
            <span
              className={cn(
                "pt-0.5 text-sm",
                isCurrent ? "font-medium text-[var(--text-primary)]" : "text-[var(--text-secondary)]"
              )}
            >
              {stage.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
