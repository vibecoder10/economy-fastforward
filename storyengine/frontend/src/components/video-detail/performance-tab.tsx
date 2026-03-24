"use client";

import { formatNumber, formatCost } from "@/lib/utils";

interface PerformanceTabProps {
  video: any;
}

export function PerformanceTab({ video }: PerformanceTabProps) {
  const hasPerformanceData = video.views > 0 || video.ctr != null;

  if (!hasPerformanceData) {
    return (
      <div className="text-center py-12" style={{ color: "var(--text-muted)" }}>
        No performance data yet. Metrics will appear after the video is published on YouTube.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top metrics */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCard label="Views" value={formatNumber(video.views || 0)} />
        <MetricCard
          label="CTR"
          value={video.ctr != null ? `${video.ctr.toFixed(1)}%` : "—"}
          alert={video.ctr != null && video.ctr < 3}
        />
        <MetricCard
          label="Retention"
          value={video.avg_retention != null ? `${video.avg_retention.toFixed(0)}%` : "—"}
        />
        <MetricCard
          label="Watch Time"
          value={
            video.avg_view_duration_seconds != null
              ? `${(video.avg_view_duration_seconds / 60).toFixed(1)} min`
              : "—"
          }
        />
      </div>

      {/* Timeline */}
      <div
        className="rounded-xl p-4"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <h3 className="text-sm font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>
          Timeline
        </h3>
        <div className="space-y-2">
          <TimelineRow label="24h" views={video.views_24h} ctr={video.ctr_24h} />
          <TimelineRow label="48h" views={video.views_48h} ctr={video.ctr_48h} />
          <TimelineRow label="7d" views={video.views_7d} />
          <TimelineRow label="30d" views={video.views_30d} />
        </div>
      </div>

      {/* Post-mortem */}
      {(video.post_mortem_48h || video.post_mortem_7d) && (
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <h3 className="text-sm font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>
            Post-Mortem
          </h3>
          {video.post_mortem_48h && (
            <div className="mb-3">
              <span className="text-xs font-medium" style={{ color: "var(--amber)" }}>48h</span>
              <p className="text-sm mt-1 whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
                {typeof video.post_mortem_48h === "string"
                  ? video.post_mortem_48h
                  : JSON.stringify(video.post_mortem_48h, null, 2)}
              </p>
            </div>
          )}
          {video.post_mortem_7d && (
            <div>
              <span className="text-xs font-medium" style={{ color: "var(--green)" }}>7d</span>
              <p className="text-sm mt-1 whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
                {typeof video.post_mortem_7d === "string"
                  ? video.post_mortem_7d
                  : JSON.stringify(video.post_mortem_7d, null, 2)}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Production cost */}
      <div
        className="rounded-xl p-4"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <h3 className="text-sm font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>
          Production Cost
        </h3>
        <p className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
          {formatCost(video.total_cost || 0)}
        </p>
        {video.performance_verdict && (
          <div className="mt-2">
            <span
              className="text-xs px-2 py-0.5 rounded"
              style={{
                background:
                  video.performance_verdict === "strong"
                    ? "rgba(58, 154, 90, 0.15)"
                    : video.performance_verdict === "weak"
                    ? "rgba(196, 69, 69, 0.15)"
                    : "rgba(212, 168, 68, 0.15)",
                color:
                  video.performance_verdict === "strong"
                    ? "var(--green)"
                    : video.performance_verdict === "weak"
                    ? "var(--red)"
                    : "var(--amber)",
              }}
            >
              {video.performance_verdict}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  alert,
}: {
  label: string;
  value: string;
  alert?: boolean;
}) {
  return (
    <div
      className="rounded-xl p-4"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {label}
      </span>
      <p
        className="text-xl font-bold mt-1"
        style={{ color: alert ? "var(--red)" : "var(--text-primary)" }}
      >
        {value}
      </p>
    </div>
  );
}

function TimelineRow({
  label,
  views,
  ctr,
}: {
  label: string;
  views?: number | null;
  ctr?: number | null;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm font-medium w-10" style={{ color: "var(--text-muted)" }}>
        {label}
      </span>
      <span className="text-sm" style={{ color: "var(--text-primary)" }}>
        {views != null ? formatNumber(views) : "—"} views
      </span>
      {ctr != null && (
        <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
          CTR: {ctr.toFixed(1)}%
        </span>
      )}
    </div>
  );
}
