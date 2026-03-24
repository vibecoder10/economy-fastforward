"use client";

import { formatCost, timeAgo } from "@/lib/utils";
import { getStageLabel, getStageColor } from "@/lib/constants";
import { ProgressDots } from "./progress-dots";
import type { VideoSummary } from "@/lib/api";

interface VideoCardProps {
  video: VideoSummary;
  onClick?: () => void;
}

function dotColor(color: string): string {
  switch (color) {
    case "green":
      return "var(--green)";
    case "amber":
      return "var(--amber)";
    case "teal":
    case "blue":
    case "cyan":
    case "violet":
    case "orange":
      return "var(--amber)";
    case "rose":
      return "var(--red)";
    default:
      return "var(--text-muted)";
  }
}

export function VideoCard({ video, onClick }: VideoCardProps) {
  const stageColor = getStageColor(video.status || "idea_logged");
  const stageLabel = getStageLabel(video.status || "idea_logged");

  return (
    <button
      onClick={onClick}
      className="flex w-full flex-col gap-2 rounded-[var(--card-radius)] border border-[var(--border)] bg-[var(--bg-card)] p-3 text-left transition-colors hover:bg-[var(--bg-card-hover)]"
    >
      {/* Title */}
      <h3 className="line-clamp-2 text-sm font-semibold leading-tight text-[var(--text-primary)]">
        {video.video_title || "Untitled"}
      </h3>

      {/* Progress dots */}
      <ProgressDots status={video.status || "idea_logged"} />

      {/* Status badge: dot + label */}
      <div className="flex items-center gap-1.5">
        <span
          className="inline-block h-2 w-2 flex-shrink-0 rounded-full"
          style={{ backgroundColor: dotColor(stageColor) }}
        />
        <span className="text-xs text-[var(--text-muted)]">{stageLabel}</span>
      </div>

      {/* Bottom row: time ago | cost */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-[var(--text-muted)]">
          {timeAgo(video.updated_at)}
        </span>
        <span className="text-xs text-[var(--text-muted)]">
          {formatCost(video.total_cost)}
        </span>
      </div>
    </button>
  );
}
