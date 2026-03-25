"use client";

import { Check } from "lucide-react";

interface ProgressStepperProps {
  steps: number;
  currentStep: number;
  completedSteps?: number[];
}

export function ProgressStepper({ steps, currentStep, completedSteps = [] }: ProgressStepperProps) {
  return (
    <div className="flex items-center gap-0">
      {Array.from({ length: steps }, (_, i) => {
        const stepNum = i + 1;
        const isCompleted = completedSteps.includes(stepNum) || stepNum < currentStep;
        const isCurrent = stepNum === currentStep;

        return (
          <div key={i} className="flex items-center">
            {/* Circle */}
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

            {/* Connector line */}
            {i < steps - 1 && (
              <div
                className="w-8 h-0.5 mx-0.5"
                style={{
                  background: isCompleted ? "var(--turquoise)" : "var(--text-tertiary)",
                  opacity: isCompleted ? 1 : 0.3,
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
