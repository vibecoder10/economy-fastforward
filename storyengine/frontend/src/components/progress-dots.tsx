"use client";

import { cn } from "@/lib/utils";
import { PIPELINE_STAGES, getStageIndex } from "@/lib/constants";

interface ProgressDotsProps {
  status: string;
  size?: "sm" | "md";
}

export function ProgressDots({ status, size = "sm" }: ProgressDotsProps) {
  const currentIndex = getStageIndex(status);
  const dotSize = size === "sm" ? "h-2 w-2" : "h-2.5 w-2.5";

  return (
    <div className="flex items-center gap-1">
      {PIPELINE_STAGES.map((stage, i) => {
        const isComplete = i < currentIndex;
        const isCurrent = i === currentIndex;

        return (
          <div
            key={stage.key}
            title={stage.label}
            className={cn(
              "rounded-full transition-all",
              dotSize,
              isCurrent && "animate-pulse-dot"
            )}
            style={{
              background: isComplete
                ? "var(--dot-complete)"
                : isCurrent
                ? "var(--dot-current)"
                : "var(--dot-pending)",
            }}
          />
        );
      })}
    </div>
  );
}
