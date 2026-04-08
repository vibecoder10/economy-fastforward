"use client";

import { PIPELINE_STAGES, getStageIndex, getStageLabel } from "@/lib/constants";
import { StageAdvancer } from "./stage-advancer";

interface PipelineActionBarProps {
  videoId: string;
  status: string;
}

const STAGE_ACTIONS: Record<string, { stage: string; label: string; cost?: string }> = {
  idea_logged: { stage: "research", label: "Run Research" },
  approved: { stage: "script", label: "Generate Script", cost: "~$0.05" },
  ready_for_scripting: { stage: "script", label: "Generate Script", cost: "~$0.05" },
  ready_for_voice: { stage: "voice", label: "Generate Voice", cost: "~$1.50" },
  ready_for_image_prompts: { stage: "prompts", label: "Generate Prompts", cost: "~$0.05" },
  ready_for_storyboards: { stage: "storyboards", label: "Generate Storyboard Prompts", cost: "~$0.05" },
  ready_for_storyboard_images: { stage: "storyboard-images", label: "Generate Storyboard Grids", cost: "~$0.50" },
  ready_for_storyboard_extraction: { stage: "storyboard-extract", label: "Extract & Upscale", cost: "~$0.50" },
  ready_for_images: { stage: "images", label: "Generate Images", cost: "~$3.00" },
  ready_for_sound_design: { stage: "sound-prompts", label: "Generate Sound Design", cost: "~$0.05" },
  ready_for_sound_effects: { stage: "sound-effects", label: "Generate Sound Effects", cost: "~$0.50" },
  ready_for_video_scripts: { stage: "video-scripts", label: "Generate Video Scripts", cost: "~$0.05" },
  ready_for_video_generation: { stage: "video-generation", label: "Generate Video Clips", cost: "~$8.00" },
  ready_for_thumbnail: { stage: "thumbnail", label: "Generate Thumbnail", cost: "~$0.15" },
  ready_to_render: { stage: "render", label: "Render Final Video" },
  rendered: { stage: "upload", label: "Upload to YouTube" },
};

const TERMINAL_STATUSES = new Set(["uploaded_draft", "uploaded", "done"]);

export function PipelineActionBar({ videoId, status }: PipelineActionBarProps) {
  const currentIndex = getStageIndex(status);
  const isTerminal = TERMINAL_STATUSES.has(status);
  const action = STAGE_ACTIONS[status];

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      {/* Progress track */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-center gap-1">
          {PIPELINE_STAGES.map((stage, i) => {
            const isComplete = i < currentIndex;
            const isCurrent = i === currentIndex;
            return (
              <div key={stage.key} className="flex-1 flex flex-col items-center gap-1">
                <div
                  className="w-full rounded-full transition-all"
                  style={{
                    height: isCurrent ? 6 : 4,
                    background: isComplete
                      ? "#1A8A7A"
                      : isCurrent
                      ? "var(--amber)"
                      : "var(--border)",
                  }}
                />
                {(isCurrent || i === 0 || i === PIPELINE_STAGES.length - 1) && (
                  <span
                    className="text-xs whitespace-nowrap"
                    style={{
                      color: isCurrent ? "var(--amber)" : "var(--text-muted)",
                      fontSize: 9,
                      fontWeight: isCurrent ? 600 : 400,
                    }}
                  >
                    {stage.label}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Action row */}
      <div
        className="flex items-center justify-between px-4 py-3"
        style={{ borderTop: "1px solid var(--border)" }}
      >
        {isTerminal ? (
          <span className="text-sm" style={{ color: "#1A8A7A" }}>
            Pipeline complete — {getStageLabel(status)}
          </span>
        ) : action ? (
          <>
            <div className="flex items-center gap-2">
              <div
                className="w-2 h-2 rounded-full animate-pulse"
                style={{ background: "var(--amber)" }}
              />
              <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                {getStageLabel(status)}
              </span>
            </div>
            <StageAdvancer
              videoId={videoId}
              stage={action.stage}
              label={action.label}
              cost={action.cost}
            />
          </>
        ) : (
          <span className="text-sm" style={{ color: "var(--text-muted)" }}>
            {getStageLabel(status)}
          </span>
        )}
      </div>
    </div>
  );
}
