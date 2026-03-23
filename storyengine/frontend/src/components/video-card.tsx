"use client";

import { cn, formatCost, timeAgo } from "@/lib/utils";
import { getStageLabel, getStageColor } from "@/lib/constants";
import { ProgressDots } from "./progress-dots";
import type { VideoSummary } from "@/lib/api";

interface VideoCardProps {
  video: VideoSummary;
  onClick?: () => void;
}

const BADGE_COLORS: Record<string, string> = {
  slate: "bg-slate-500/20 text-slate-400",
  blue: "bg-blue-500/20 text-blue-400",
  cyan: "bg-cyan-500/20 text-cyan-400",
  amber: "bg-amber-500/20 text-amber-400",
  violet: "bg-violet-500/20 text-violet-400",
  orange: "bg-orange-500/20 text-orange-400",
  rose: "bg-rose-500/20 text-rose-400",
  emerald: "bg-emerald-500/20 text-emerald-400",
  green: "bg-green-500/20 text-green-400",
};

export function VideoCard({ video, onClick }: VideoCardProps) {
  const stageColor = getStageColor(video.status || "idea_logged");
  const stageLabel = getStageLabel(video.status || "idea_logged");

  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 text-left transition-colors hover:bg-[var(--surface-elevated)]"
    >
      {/* Thumbnail */}
      <div className="h-[45px] w-[80px] flex-shrink-0 overflow-hidden rounded-lg bg-[var(--surface-elevated)]">
        {video.thumbnail_url ? (
          <img
            src={video.thumbnail_url}
            alt=""
            className="h-full w-full object-cover"
          />
        ) : (
          <div
            className="flex h-full w-full items-center justify-center text-xs text-[var(--text-secondary)]"
            style={{ background: `${video.accent_color}15` }}
          >
            {(video.video_title || "?").charAt(0)}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <h3 className="line-clamp-2 text-sm font-medium leading-tight">{video.video_title || "Untitled"}</h3>
        <div className="flex items-center gap-2">
          <ProgressDots status={video.status || "idea_logged"} />
          <span
            className={cn(
              "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
              BADGE_COLORS[stageColor] || "bg-slate-500/20 text-slate-400"
            )}
          >
            {stageLabel}
          </span>
        </div>
      </div>

      {/* Right side info */}
      <div className="flex flex-shrink-0 flex-col items-end gap-1 text-right">
        <span className="text-xs text-[var(--text-secondary)]">{formatCost(video.total_cost)}</span>
        <span className="text-[10px] text-[var(--text-secondary)]">{timeAgo(video.updated_at)}</span>
      </div>
    </button>
  );
}
