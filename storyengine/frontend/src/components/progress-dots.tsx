"use client";

import { cn } from "@/lib/utils";
import { PIPELINE_STAGES, getStageIndex } from "@/lib/constants";

interface ProgressDotsProps {
  status: string;
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
}

export function ProgressDots({ status, size = "sm", showLabel = false }: ProgressDotsProps) {
  const currentIndex = getStageIndex(status);
  const dotSize = size === "sm" ? "h-2.5 w-2.5" : size === "md" ? "h-3.5 w-3.5" : "h-4 w-4";
  const gap = size === "sm" ? "gap-1.5" : "gap-2";

  const currentStage = PIPELINE_STAGES[currentIndex];

  return (
    <div className="flex flex-col gap-1">
      <div className={`flex items-center ${gap}`}>
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
                isCurrent && "scale-125",
              )}
              style={{
                background: isComplete
                  ? "var(--dot-complete)"
                  : isCurrent
                  ? "var(--dot-current)"
                  : "var(--dot-pending)",
                boxShadow: isCurrent ? "0 0 0 2px var(--bg-primary), 0 0 0 4px rgba(212, 168, 68, 0.4)" : undefined,
              }}
            />
          );
        })}
      </div>
      {showLabel && currentStage && (
        <span className="text-xs font-medium" style={{ color: "var(--dot-current)" }}>
          {currentStage.label}
        </span>
      )}
    </div>
  );
}
