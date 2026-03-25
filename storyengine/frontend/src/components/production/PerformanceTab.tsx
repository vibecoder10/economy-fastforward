"use client";

import { GlassCard } from "@/components/ui/GlassCard";
import { VerdictBadge } from "@/components/ui/VerdictBadge";
import { StatCard } from "@/components/ui/StatCard";
import { Eye, MousePointer, Clock, TrendingUp } from "lucide-react";
import type { Video } from "@/lib/types";

interface PerformanceTabProps {
  video: Video;
}

function formatViews(n: number) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toString();
}

export function PerformanceTab({ video }: PerformanceTabProps) {
  const hasData = video.views !== undefined;

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

  return (
    <div className="space-y-6">
      {/* Verdict */}
      <div className="flex items-center gap-4">
        <span className="text-sm" style={{ color: "var(--text-secondary)" }}>Performance Verdict:</span>
        {video.verdict && <VerdictBadge verdict={video.verdict} />}
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Views" value={formatViews(video.views || 0)} color="var(--turquoise)" icon={Eye} />
        <StatCard label="CTR" value={`${(video.ctr || 0).toFixed(1)}%`} color="var(--gold)" icon={MousePointer} trend={(video.ctr || 0) > 5 ? "up" : "down"} />
        <StatCard label="Retention" value={`${video.retention || 0}%`} color="var(--green)" icon={Clock} />
        <StatCard label="Watch Time" value={`${(video.watchTimeHrs || 0).toLocaleString()}h`} color="var(--purple)" icon={TrendingUp} />
      </div>

      {/* Details */}
      <GlassCard className="p-5">
        <h3 className="text-xs font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
          Video Details
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: "Upload Date", value: video.uploadDate || "—" },
            { label: "Duration", value: `${video.videoLengthMin || 0} min` },
            { label: "Framework", value: video.framework || "—" },
            { label: "Production Cost", value: `$${(video.estimatedCost || 0).toFixed(2)}` },
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
