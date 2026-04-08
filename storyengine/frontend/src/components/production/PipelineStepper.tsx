"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";
import { Check } from "lucide-react";

/**
 * 13-stage pipeline stepper with live status.
 * Stages map to the full production pipeline:
 * idea → research → script → voice → storyboard → images → sound →
 * video clips → thumbnail → render → rendered → upload → published
 */
const STEPPER_STAGES = [
  { key: "idea_logged", label: "Idea" },
  { key: "research", label: "Research" },
  { key: "ready_for_scripting", label: "Script" },
  { key: "ready_for_voice", label: "Voice" },
  { key: "ready_for_storyboards", label: "Storyboard" },
  { key: "ready_for_images", label: "Images" },
  { key: "ready_for_sound", label: "Sound" },
  { key: "ready_for_video", label: "Clips" },
  { key: "ready_for_thumbnail", label: "Thumbnail" },
  { key: "ready_to_render", label: "Render" },
  { key: "rendered", label: "Rendered" },
  { key: "uploaded_draft", label: "Upload" },
  { key: "done", label: "Published" },
] as const;

/** Map raw pipeline status to stepper index (0-12). */
function getStepperIndex(status: string): number {
  // Direct match
  const direct = STEPPER_STAGES.findIndex((s) => s.key === status);
  if (direct >= 0) return direct;

  // Map sub-statuses to the right stepper stage
  const MAP: Record<string, number> = {
    approved: 1,
    researching: 1,
    scripting: 2,
    needs_script_review: 2,
    voice: 3,
    ready_for_image_prompts: 4,
    ready_for_storyboard_images: 4,
    ready_for_storyboard_extraction: 4,
    ready_for_sound_design: 6,
    ready_for_sound_effects: 6,
    ready_for_video_scripts: 7,
    ready_for_video_generation: 7,
    rendering: 9,
    uploaded: 11,
    published: 12,
  };
  return MAP[status] ?? 0;
}

interface PipelineStepperProps {
  status: string;
  /** Optional: override current index from SSE stage_change event. */
  liveStatus?: string | null;
  className?: string;
  /** Compact mode hides labels on mobile. */
  compact?: boolean;
}

export function PipelineStepper({
  status,
  liveStatus,
  className = "",
  compact = false,
}: PipelineStepperProps) {
  const effectiveStatus = liveStatus || status;
  const currentIdx = useMemo(
    () => getStepperIndex(effectiveStatus),
    [effectiveStatus],
  );

  return (
    <div
      className={`flex items-start overflow-x-auto scrollbar-hide ${className}`}
      role="progressbar"
      aria-valuenow={currentIdx + 1}
      aria-valuemax={STEPPER_STAGES.length}
    >
      {STEPPER_STAGES.map((stage, i) => {
        const isCompleted = i < currentIdx;
        const isCurrent = i === currentIdx;
        const isFuture = i > currentIdx;

        return (
          <div key={stage.key} className="flex items-start shrink-0">
            {/* Step circle + label */}
            <div className="flex flex-col items-center gap-1" style={{ minWidth: compact ? 28 : 36 }}>
              <motion.div
                initial={false}
                animate={{
                  scale: isCurrent ? [1, 1.15, 1] : 1,
                  transition: isCurrent
                    ? { repeat: Infinity, duration: 2, ease: "easeInOut" }
                    : { duration: 0.3 },
                }}
                className="flex items-center justify-center rounded-full text-[10px] font-semibold"
                style={{
                  width: compact ? 24 : 28,
                  height: compact ? 24 : 28,
                  background: isCompleted
                    ? "var(--turquoise)"
                    : isCurrent
                      ? "rgba(255,120,73,0.15)"
                      : "var(--bg-elevated)",
                  border: isCompleted
                    ? "2px solid var(--turquoise)"
                    : isCurrent
                      ? "2px solid var(--orange)"
                      : "2px solid var(--border-subtle)",
                  color: isCompleted
                    ? "var(--bg-void)"
                    : isCurrent
                      ? "var(--orange)"
                      : "var(--text-tertiary)",
                }}
              >
                {isCompleted ? <Check size={12} strokeWidth={3} /> : i + 1}
              </motion.div>

              {!compact && (
                <span
                  className="text-[8px] font-medium uppercase tracking-wider whitespace-nowrap"
                  style={{
                    color: isCompleted
                      ? "var(--turquoise)"
                      : isCurrent
                        ? "var(--orange)"
                        : "var(--text-tertiary)",
                  }}
                >
                  {stage.label}
                </span>
              )}
            </div>

            {/* Connector line */}
            {i < STEPPER_STAGES.length - 1 && (
              <div
                className="shrink-0"
                style={{
                  width: compact ? 12 : 16,
                  height: 2,
                  marginTop: compact ? 11 : 13,
                  background: isCompleted
                    ? "var(--turquoise)"
                    : "var(--border-subtle)",
                  opacity: isCompleted ? 1 : 0.5,
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
