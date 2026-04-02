"use client";

import { GlassCard } from "@/components/ui/GlassCard";
import { VerdictBadge } from "@/components/ui/VerdictBadge";
import { StatCard } from "@/components/ui/StatCard";
import { Eye, MousePointer, Clock, TrendingUp } from "lucide-react";
import { formatNumber, formatCost } from "@/lib/utils";
import type { VideoDetail } from "@/lib/api";

interface PerformanceTabProps {
  video: VideoDetail & {
    verdict?: "hit" | "steady" | "underperformed";
    watchTimeHrs?: number;
    uploadDate?: string;
    videoLengthMin?: number;
    framework?: string;
    estimatedCost?: number;
  };
}

export function PerformanceTab({ video }: PerformanceTabProps) {
  const hasData = video.views !== undefined && video.views > 0;

  if (!hasData) {
    return (
      <GlassCard className="p-12 text-center">
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          No Performance Data Yet
        </p>
        <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
          Performance metrics will appear after the video is published to YouTube.
        </p>
      </GlassCard>
    );
  }

  // Snapshot timeline data
  const snapshots = [
    { label: "24h", views: video.views_24h, ctr: null, retention: null },
    { label: "48h", views: video.views_48h, ctr: video.ctr_48h, retention: video.retention_48h },
    { label: "7d", views: video.views_7d, ctr: null, retention: null },
    { label: "30d", views: video.views_30d, ctr: null, retention: null },
  ];

  const hasSnapshots = snapshots.some((s) => s.views != null || s.ctr != null);

  // Additional CTR snapshots
  const ctrSnapshots = [
    { label: "12h", value: video.ctr_12h },
    { label: "24h", value: video.ctr_24h },
    { label: "48h", value: video.ctr_48h },
  ];
  const hasCtrSnapshots = ctrSnapshots.some((s) => s.value != null);

  return (
    <div className="space-y-6">
      {/* Verdict */}
      {video.verdict && (
        <div className="flex items-center gap-4">
          <span className="text-sm" style={{ color: "var(--text-secondary)" }}>Performance Verdict:</span>
          <VerdictBadge verdict={video.verdict} />
        </div>
      )}

      {/* Lifetime stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Views" value={formatNumber(video.views || 0)} color="var(--turquoise)" icon={Eye} />
        <StatCard label="CTR" value={`${(video.ctr || 0).toFixed(1)}%`} color="var(--gold)" icon={MousePointer} trend={(video.ctr || 0) > 5 ? "up" : "down"} />
        <StatCard label="Retention" value={`${video.avg_retention || 0}%`} color="var(--green)" icon={Clock} />
        <StatCard label="Impressions" value={formatNumber(video.impressions || 0)} color="var(--purple)" icon={TrendingUp} />
      </div>

      {/* View snapshots timeline */}
      {hasSnapshots && (
        <GlassCard className="p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
            Views Over Time
          </h3>
          <div className="grid grid-cols-4 gap-3">
            {snapshots.map((snap) => (
              <div
                key={snap.label}
                className="rounded-lg p-3 text-center"
                style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-subtle)" }}
              >
                <p className="text-[10px] uppercase tracking-wider mb-1 font-mono" style={{ color: "var(--text-tertiary)" }}>
                  {snap.label}
                </p>
                <p className="text-lg font-mono font-medium" style={{ color: "var(--text-primary)" }}>
                  {snap.views != null ? formatNumber(snap.views) : "—"}
                </p>
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      {/* CTR snapshots */}
      {hasCtrSnapshots && (
        <GlassCard className="p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
            CTR Over Time
          </h3>
          <div className="grid grid-cols-3 gap-3">
            {ctrSnapshots.map((snap) => {
              const value = snap.value;
              const color = value != null
                ? value >= 5 ? "var(--green)" : value >= 3.5 ? "var(--gold)" : "var(--red)"
                : "var(--text-tertiary)";
              return (
                <div
                  key={snap.label}
                  className="rounded-lg p-3 text-center"
                  style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-subtle)" }}
                >
                  <p className="text-[10px] uppercase tracking-wider mb-1 font-mono" style={{ color: "var(--text-tertiary)" }}>
                    {snap.label}
                  </p>
                  <p className="text-lg font-mono font-medium" style={{ color }}>
                    {value != null ? `${value.toFixed(1)}%` : "—"}
                  </p>
                </div>
              );
            })}
          </div>
          {video.retention_48h != null && (
            <div className="mt-3 pt-3" style={{ borderTop: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center justify-between">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>Retention @ 48h</span>
                <span className="text-sm font-mono font-medium" style={{ color: "var(--green)" }}>
                  {video.retention_48h.toFixed(1)}%
                </span>
              </div>
            </div>
          )}
        </GlassCard>
      )}

      {/* Details */}
      <GlassCard className="p-5">
        <h3 className="text-xs font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
          Video Details
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: "Upload Date", value: video.uploadDate || "—" },
            { label: "Duration", value: `${video.video_length_minutes || video.videoLengthMin || 0} min` },
            { label: "Framework", value: video.framework_angle || video.framework || "—" },
            { label: "Production Cost", value: formatCost(video.total_cost || video.estimatedCost || 0) },
          ].map((item) => (
            <div key={item.label}>
              <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>{item.label}</p>
              <p className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>{item.value}</p>
            </div>
          ))}
        </div>
      </GlassCard>
    </div>
  );
}
