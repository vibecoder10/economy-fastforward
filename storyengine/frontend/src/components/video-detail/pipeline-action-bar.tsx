"use client";

import { getStageLabel } from "@/lib/constants";
import { StageAdvancer } from "./stage-advancer";

interface PipelineActionBarProps {
  videoId: string;
  status: string;
}

// Map each pipeline status to the stage endpoint + button label
const STAGE_ACTIONS: Record<string, { stage: string; label: string; cost?: string }> = {
  idea_logged: { stage: "research", label: "Run Research" },
  approved: { stage: "script", label: "Generate Script", cost: "~$0.05" },
  ready_for_scripting: { stage: "script", label: "Generate Script", cost: "~$0.05" },
  ready_for_voice: { stage: "voice", label: "Generate Voice", cost: "~$1.50" },
  ready_for_image_prompts: { stage: "prompts", label: "Generate Image Prompts", cost: "~$0.05" },
  ready_for_storyboards: { stage: "storyboards", label: "Generate Storyboard Prompts", cost: "~$0.05" },
  ready_for_storyboard_images: { stage: "storyboard-images", label: "Generate Storyboard Grids", cost: "~$0.50" },
  ready_for_storyboard_extraction: { stage: "storyboard-extract", label: "Extract & Upscale Panels", cost: "~$0.50" },
  ready_for_images: { stage: "images", label: "Generate Images", cost: "~$3.00" },
  ready_for_sound_design: { stage: "sound-prompts", label: "Generate Sound Design", cost: "~$0.05" },
  ready_for_sound_effects: { stage: "sound-effects", label: "Generate Sound Effects", cost: "~$0.50" },
  ready_for_video_scripts: { stage: "video-scripts", label: "Generate Video Scripts", cost: "~$0.05" },
  ready_for_video_generation: { stage: "video-generation", label: "Generate Video Clips", cost: "~$8.00" },
  ready_for_thumbnail: { stage: "thumbnail", label: "Generate Thumbnail", cost: "~$0.15" },
  ready_to_render: { stage: "render", label: "Render Final Video" },
};

// Statuses where pipeline is complete — no action needed
const TERMINAL_STATUSES = new Set(["rendered", "uploaded_draft", "uploaded", "done"]);

export function PipelineActionBar({ videoId, status }: PipelineActionBarProps) {
  if (TERMINAL_STATUSES.has(status)) {
    return (
      <div
        className="flex items-center justify-between rounded-xl px-4 py-3"
        style={{ background: "rgba(26, 138, 122, 0.08)", border: "1px solid rgba(26, 138, 122, 0.2)" }}
      >
        <span className="text-sm" style={{ color: "#1A8A7A" }}>
          Pipeline complete — {getStageLabel(status)}
        </span>
      </div>
    );
  }

  const action = STAGE_ACTIONS[status];
  if (!action) {
    return (
      <div
        className="flex items-center justify-between rounded-xl px-4 py-3"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <span className="text-sm" style={{ color: "var(--text-muted)" }}>
          Status: {getStageLabel(status)}
        </span>
      </div>
    );
  }

  return (
    <div
      className="flex items-center justify-between rounded-xl px-4 py-3"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
          Next step:
        </span>
        <span className="text-xs px-2 py-0.5 rounded" style={{ background: "rgba(212, 168, 68, 0.1)", color: "var(--amber)" }}>
          {getStageLabel(status)}
        </span>
      </div>
      <StageAdvancer
        videoId={videoId}
        stage={action.stage}
        label={action.label}
        cost={action.cost}
      />
    </div>
  );
}
