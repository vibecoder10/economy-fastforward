"use client";

import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { VerdictBadge } from "@/components/ui/VerdictBadge";
import { StatCard } from "@/components/ui/StatCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { Eye, MousePointer, Clock, TrendingUp, ChevronDown, AlertTriangle, CheckCircle, MinusCircle, Zap, Shield, Sparkles, X, Check } from "lucide-react";
import { formatNumber, formatCost, timeAgo } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { acceptSuggestion, rejectSuggestion } from "@/lib/api";
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
  const hasSuggestion = video.suggestion_status !== "accepted" && video.suggestion_status !== "rejected" &&
    (video.suggested_script || video.suggested_title);

  if (!hasData && !hasSuggestion) {
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
      {/* Agent Suggestion */}
      {hasSuggestion && (
        <SuggestionCard video={video} />
      )}

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

      {/* Agent Quality Scores */}
      {(video.agent_hook_score != null || video.agent_body_score != null || video.agent_tier != null) && (
        <GlassCard className="p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
            Agent Quality Scores
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {video.agent_hook_score != null && (
              <ScoreCard label="Hook Score" value={video.agent_hook_score} max={10} icon={Zap} />
            )}
            {video.agent_body_score != null && (
              <ScoreCard label="Body Score" value={video.agent_body_score} max={10} icon={Shield} />
            )}
            {video.agent_tier != null && (
              <div
                className="rounded-lg p-3 text-center"
                style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-subtle)" }}
              >
                <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>Tier</p>
                <p
                  className="text-lg font-mono font-semibold uppercase"
                  style={{ color: video.agent_tier === "premium" ? "var(--gold)" : "var(--turquoise)" }}
                >
                  {video.agent_tier}
                </p>
              </div>
            )}
            {video.agent_cost != null && (
              <div
                className="rounded-lg p-3 text-center"
                style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-subtle)" }}
              >
                <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>Agent Cost</p>
                <p className="text-lg font-mono font-medium" style={{ color: "var(--gold)" }}>
                  {formatCost(video.agent_cost)}
                </p>
              </div>
            )}
          </div>
        </GlassCard>
      )}

      {/* Post-Mortem Analysis */}
      {(video.post_mortem_48h || video.post_mortem_7d) && (
        <div className="space-y-4">
          {video.post_mortem_48h && (
            <PostMortemSection label="48-Hour Analysis" raw={video.post_mortem_48h} />
          )}
          {video.post_mortem_7d && (
            <PostMortemSection label="7-Day Analysis" raw={video.post_mortem_7d} />
          )}
        </div>
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

interface PostMortemData {
  ctr_verdict?: string;
  retention_verdict?: string;
  overall_verdict?: string;
  recommendations?: string[];
  analyzed_at?: string;
  metrics?: Record<string, number | null>;
}

function parsePostMortem(raw: string): PostMortemData | null {
  try {
    const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
    return parsed as PostMortemData;
  } catch {
    return null;
  }
}

const VERDICT_ICON: Record<string, { icon: typeof CheckCircle; color: string }> = {
  strong: { icon: CheckCircle, color: "var(--green)" },
  average: { icon: MinusCircle, color: "var(--gold)" },
  weak: { icon: AlertTriangle, color: "var(--red)" },
};

function PostMortemSection({ label, raw }: { label: string; raw: string }) {
  const [open, setOpen] = useState(false);
  const data = parsePostMortem(raw);

  if (!data) return null;

  const overall = data.overall_verdict || "average";
  const vi = VERDICT_ICON[overall] || VERDICT_ICON.average;
  const Icon = vi.icon;

  return (
    <GlassCard className="p-5">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between"
      >
        <div className="flex items-center gap-3">
          <Icon size={18} style={{ color: vi.color }} />
          <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
            {label}
          </h3>
          <span
            className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full font-mono"
            style={{
              color: vi.color,
              background: `color-mix(in srgb, ${vi.color} 15%, transparent)`,
            }}
          >
            {overall}
          </span>
        </div>
        <ChevronDown
          size={16}
          style={{
            color: "var(--text-tertiary)",
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 0.2s",
          }}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="pt-4 space-y-4">
              {/* Verdict pills */}
              <div className="flex gap-4">
                {data.ctr_verdict && (
                  <VerdictPill label="CTR" verdict={data.ctr_verdict} />
                )}
                {data.retention_verdict && (
                  <VerdictPill label="Retention" verdict={data.retention_verdict} />
                )}
              </div>

              {/* Recommendations */}
              {data.recommendations && data.recommendations.length > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
                    Recommendations
                  </p>
                  <ul className="space-y-1.5">
                    {data.recommendations.map((rec, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                        <span style={{ color: "var(--gold)" }}>•</span>
                        {rec}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Metrics */}
              {data.metrics && Object.keys(data.metrics).length > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
                    Metrics at Analysis
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    {Object.entries(data.metrics).map(([key, val]) => (
                      <div
                        key={key}
                        className="rounded-lg p-2 text-center"
                        style={{ background: "rgba(255,255,255,0.03)" }}
                      >
                        <p className="text-[10px] uppercase tracking-wider font-mono" style={{ color: "var(--text-tertiary)" }}>
                          {key.replace(/_/g, " ")}
                        </p>
                        <p className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>
                          {val != null ? (typeof val === "number" && val < 100 ? val.toFixed(1) : formatNumber(val as number)) : "—"}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Analyzed timestamp */}
              {data.analyzed_at && (
                <p className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                  Analyzed {timeAgo(data.analyzed_at)}
                </p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </GlassCard>
  );
}

function ScoreCard({ label, value, max, icon: Icon }: { label: string; value: number; max: number; icon: typeof Zap }) {
  const pct = Math.min((value / max) * 100, 100);
  const color = pct >= 70 ? "var(--green)" : pct >= 50 ? "var(--gold)" : "var(--red)";
  return (
    <div
      className="rounded-lg p-3 text-center"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-subtle)" }}
    >
      <div className="flex items-center justify-center gap-1.5 mb-1">
        <Icon size={12} style={{ color: "var(--text-tertiary)" }} />
        <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>{label}</p>
      </div>
      <p className="text-lg font-mono font-medium" style={{ color }}>
        {value.toFixed(1)}<span className="text-xs" style={{ color: "var(--text-tertiary)" }}>/{max}</span>
      </p>
      <div className="mt-2 h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

function VerdictPill({ label, verdict }: { label: string; verdict: string }) {
  const vi = VERDICT_ICON[verdict] || VERDICT_ICON.average;
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
        {label}:
      </span>
      <span
        className="text-[11px] font-mono px-2 py-0.5 rounded-full"
        style={{
          color: vi.color,
          background: `color-mix(in srgb, ${vi.color} 15%, transparent)`,
        }}
      >
        {verdict}
      </span>
    </div>
  );
}

function SuggestionCard({ video }: { video: VideoDetail }) {
  const [selectedFields, setSelectedFields] = useState<string[]>([]);
  const [showScript, setShowScript] = useState(false);
  const queryClient = useQueryClient();

  const acceptMutation = useMutation({
    mutationFn: () => acceptSuggestion(video.id, selectedFields),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
  });

  const rejectMutation = useMutation({
    mutationFn: () => rejectSuggestion(video.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
  });

  const toggleField = (field: string) => {
    setSelectedFields((prev) =>
      prev.includes(field) ? prev.filter((f) => f !== field) : [...prev, field]
    );
  };

  const scores = video.suggestion_scores;

  return (
    <GlassCard className="p-5" style={{ borderColor: "rgba(212, 168, 68, 0.3)" }}>
      <div className="flex items-center gap-2 mb-4">
        <Sparkles size={16} style={{ color: "var(--gold)" }} />
        <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--gold)" }}>
          Agent Suggestion
        </h3>
        {video.suggestion_source && (
          <span
            className="text-[10px] font-mono px-2 py-0.5 rounded-full"
            style={{ color: "var(--text-secondary)", background: "rgba(255,255,255,0.05)" }}
          >
            via {video.suggestion_source}
          </span>
        )}
      </div>

      <div className="space-y-3">
        {/* Suggested Title */}
        {video.suggested_title && (
          <div
            className="rounded-lg p-3 flex items-start gap-3 cursor-pointer"
            style={{ background: "rgba(255,255,255,0.03)", border: `1px solid ${selectedFields.includes("title") ? "var(--gold)" : "var(--border-subtle)"}` }}
            onClick={() => toggleField("title")}
          >
            <div
              className="w-4 h-4 rounded border flex-shrink-0 mt-0.5 flex items-center justify-center"
              style={{ borderColor: selectedFields.includes("title") ? "var(--gold)" : "var(--text-tertiary)", background: selectedFields.includes("title") ? "var(--gold)" : "transparent" }}
            >
              {selectedFields.includes("title") && <Check size={10} style={{ color: "var(--bg-void)" }} />}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>Suggested Title</p>
              <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{video.suggested_title}</p>
            </div>
          </div>
        )}

        {/* Suggested Script */}
        {video.suggested_script && (
          <div
            className="rounded-lg p-3"
            style={{ background: "rgba(255,255,255,0.03)", border: `1px solid ${selectedFields.includes("script") ? "var(--gold)" : "var(--border-subtle)"}` }}
          >
            <div className="flex items-start gap-3 cursor-pointer" onClick={() => toggleField("script")}>
              <div
                className="w-4 h-4 rounded border flex-shrink-0 mt-0.5 flex items-center justify-center"
                style={{ borderColor: selectedFields.includes("script") ? "var(--gold)" : "var(--text-tertiary)", background: selectedFields.includes("script") ? "var(--gold)" : "transparent" }}
              >
                {selectedFields.includes("script") && <Check size={10} style={{ color: "var(--bg-void)" }} />}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>Suggested Script</p>
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  {showScript ? video.suggested_script : `${video.suggested_script.slice(0, 200)}...`}
                </p>
              </div>
            </div>
            {video.suggested_script.length > 200 && (
              <button
                onClick={() => setShowScript(!showScript)}
                className="text-[10px] mt-2 ml-7"
                style={{ color: "var(--turquoise)" }}
              >
                {showScript ? "Show less" : "Show full script"}
              </button>
            )}
          </div>
        )}

        {/* Scores */}
        {scores && (
          <div className="flex gap-4 mt-2">
            {scores.hook != null && (
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Hook:</span>
                <span className="text-sm font-mono" style={{ color: "var(--turquoise)" }}>{scores.hook}/10</span>
              </div>
            )}
            {scores.body != null && (
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Body:</span>
                <span className="text-sm font-mono" style={{ color: "var(--turquoise)" }}>{scores.body}/10</span>
              </div>
            )}
            {scores.reasoning && (
              <p className="text-[11px] flex-1" style={{ color: "var(--text-tertiary)" }}>{scores.reasoning}</p>
            )}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3 mt-4 pt-4" style={{ borderTop: "1px solid var(--border-subtle)" }}>
        <ActionButton
          variant="filled"
          onClick={() => acceptMutation.mutate()}
          disabled={selectedFields.length === 0 || acceptMutation.isPending}
          icon={Check}
        >
          {acceptMutation.isPending ? "Accepting..." : `Accept${selectedFields.length > 0 ? ` (${selectedFields.length})` : ""}`}
        </ActionButton>
        <ActionButton
          variant="warning"
          onClick={() => rejectMutation.mutate()}
          disabled={rejectMutation.isPending}
          icon={X}
        >
          {rejectMutation.isPending ? "Rejecting..." : "Reject All"}
        </ActionButton>
      </div>
    </GlassCard>
  );
}
