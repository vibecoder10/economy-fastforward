"use client";

import { Check } from "lucide-react";

interface ProgressStepperProps {
  steps: number;
  currentStep: number;
  completedSteps?: number[];
  labels?: string[];
}

export function ProgressStepper({ steps, currentStep, completedSteps = [], labels }: ProgressStepperProps) {
  return (
    <div className="flex items-center gap-0">
      {Array.from({ length: steps }, (_, i) => {
        const stepNum = i + 1;
        const isCompleted = completedSteps.includes(stepNum) || stepNum < currentStep;
        const isCurrent = stepNum === currentStep;

        return (
          <div key={i} className="flex items-center">
            {/* Step circle + label */}
            <div className="flex flex-col items-center gap-1">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium transition-all ${
                  isCurrent ? "animate-pulse-glow" : ""
                }`}
                style={{
                  background: isCompleted
                    ? "var(--turquoise)"
                    : isCurrent
                    ? "transparent"
                    : "var(--bg-elevated)",
                  border: isCurrent
                    ? "2px solid var(--orange)"
                    : isCompleted
                    ? "2px solid var(--turquoise)"
                    : "2px solid var(--text-tertiary)",
                  color: isCompleted ? "var(--bg-void)" : isCurrent ? "var(--orange)" : "var(--text-tertiary)",
                }}
              >
                {isCompleted ? <Check size={14} strokeWidth={3} /> : stepNum}
              </div>
              {labels?.[i] && (
                <span
                  className="text-[9px] font-medium whitespace-nowrap"
                  style={{ color: isCurrent ? "var(--orange)" : isCompleted ? "var(--turquoise)" : "var(--text-tertiary)" }}
                >
                  {labels[i]}
                </span>
              )}
            </div>

            {/* Connector line */}
            {i < steps - 1 && (
              <div
                className="w-8 h-0.5 mx-0.5"
                style={{
                  background: isCompleted ? "var(--turquoise)" : "var(--text-tertiary)",
                  opacity: isCompleted ? 1 : 0.3,
                  marginBottom: labels ? "1.25rem" : 0,
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
