"use client";

import { cn } from "@/lib/utils";
import { PIPELINE_STAGES, getStageIndex } from "@/lib/constants";

interface ProgressDotsProps {
  status: string;
  size?: "sm" | "md";
}

const DOT_COLORS: Record<string, string> = {
  slate: "bg-slate-500",
  blue: "bg-blue-500",
  cyan: "bg-cyan-500",
  amber: "bg-amber-500",
  violet: "bg-violet-500",
  orange: "bg-orange-500",
  rose: "bg-rose-500",
  emerald: "bg-emerald-500",
  green: "bg-green-500",
};

export function ProgressDots({ status, size = "sm" }: ProgressDotsProps) {
  const currentIndex = getStageIndex(status);
  const dotSize = size === "sm" ? "h-2 w-2" : "h-2.5 w-2.5";

  return (
    <div className="flex items-center gap-1">
      {PIPELINE_STAGES.map((stage, i) => {
        const isDone = i < currentIndex;
        const isCurrent = i === currentIndex;
        const isPending = i > currentIndex;

        return (
          <div
            key={stage.key}
            title={stage.label}
            className={cn(
              "rounded-full transition-all",
              dotSize,
              isDone && `${DOT_COLORS[stage.color] || "bg-green-500"}`,
              isCurrent && `${DOT_COLORS[stage.color] || "bg-amber-500"} animate-pulse-dot`,
              isPending && "bg-white/10"
            )}
          />
        );
      })}
    </div>
  );
}
