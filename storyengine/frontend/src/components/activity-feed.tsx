"use client";

import { cn, timeAgo } from "@/lib/utils";
import type { ActivityEntry } from "@/lib/api";

const BOT_COLORS: Record<string, string> = {
  script_bot: "bg-blue-500",
  voice_bot: "bg-cyan-500",
  image_bot: "bg-violet-500",
  image_prompt_bot: "bg-purple-500",
  video_bot: "bg-rose-500",
  thumbnail_bot: "bg-orange-500",
  render: "bg-emerald-500",
  upload: "bg-green-500",
  autopilot: "bg-[var(--accent)]",
};

const STATUS_STYLES: Record<string, string> = {
  started: "text-blue-400",
  running: "text-amber-400",
  completed: "text-green-400",
  failed: "text-[var(--error)]",
};

interface ActivityFeedProps {
  entries: ActivityEntry[];
}

export function ActivityFeed({ entries }: ActivityFeedProps) {
  if (entries.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-[var(--text-secondary)]">
        No activity yet
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {entries.map((entry) => (
        <div
          key={entry.id}
          className={cn(
            "rounded-xl border bg-[var(--surface)] p-3 transition-colors",
            entry.status === "failed"
              ? "border-[var(--error)]/30"
              : "border-[var(--border)]"
          )}
        >
          <div className="flex items-start gap-3">
            {/* Bot indicator */}
            <div
              className={cn(
                "mt-0.5 h-2.5 w-2.5 flex-shrink-0 rounded-full",
                BOT_COLORS[entry.bot_name] || "bg-slate-500"
              )}
            />

            {/* Content */}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{entry.bot_name.replace(/_/g, " ")}</span>
                <span className={cn("text-xs font-medium", STATUS_STYLES[entry.status] || "text-[var(--text-secondary)]")}>
                  {entry.status}
                </span>
              </div>
              {entry.video_title && (
                <p className="mt-0.5 text-xs text-[var(--text-secondary)] line-clamp-1">
                  {entry.video_title}
                </p>
              )}
              {entry.message && entry.status === "failed" && (
                <p className="mt-1 rounded bg-[var(--error)]/10 px-2 py-1 text-xs text-[var(--error)]">
                  {entry.message}
                </p>
              )}
            </div>

            {/* Meta */}
            <div className="flex flex-shrink-0 flex-col items-end gap-0.5">
              <span className="text-[10px] text-[var(--text-secondary)]">
                {timeAgo(entry.created_at)}
              </span>
              {entry.cost > 0 && (
                <span className="text-[10px] text-[var(--text-secondary)]">
                  ${entry.cost.toFixed(2)}
                </span>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
