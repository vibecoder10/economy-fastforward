"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  Brain, Sparkles, FileText, MessageSquare, Loader2,
  ToggleLeft, ToggleRight, TrendingUp, ChevronDown,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getLearnings, extractLearnings, analyzeCompetitorTitles,
  analyzeTranscripts, toggleLearning, getAutopilotLearnings,
  type LearningRecord, type ExtractionResult, type Learning,
} from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorCard } from "@/components/ui/ErrorCard";

const container = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.08 } } };
const item = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0, transition: { duration: 0.5 } } };

const CATEGORIES = [
  { value: "", label: "All" },
  { value: "title", label: "Title" },
  { value: "hook", label: "Hook" },
  { value: "framework", label: "Framework" },
  { value: "script", label: "Script" },
];

const CATEGORY_COLORS: Record<string, string> = {
  title: "var(--gold)",
  hook: "var(--turquoise)",
  framework: "var(--purple)",
  script: "var(--blue, #5B8DEF)",
};

function getVerdict(confidence: number): { label: string; color: string } {
  if (confidence >= 60) return { label: "PROVEN", color: "var(--green)" };
  if (confidence <= 40) return { label: "AVOID", color: "var(--red)" };
  return { label: "TESTING", color: "var(--gold)" };
}

export default function LearningsPage() {
  const queryClient = useQueryClient();
  const [category, setCategory] = useState("");
  const [showInactive, setShowInactive] = useState(false);

  const { data: learnings, isLoading } = useQuery({
    queryKey: ["learnings", category, showInactive],
    queryFn: () => getLearnings(category || undefined, !showInactive),
  });

  const extractMutation = useMutation({
    mutationFn: extractLearnings,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["learnings"] }),
  });

  const titlesMutation = useMutation({
    mutationFn: analyzeCompetitorTitles,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["learnings"] }),
  });

  const transcriptsMutation = useMutation({
    mutationFn: analyzeTranscripts,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["learnings"] }),
  });

  const toggleMutation = useMutation({
    mutationFn: (id: string) => toggleLearning(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["learnings"] }),
  });

  const { data: titleInsights, isLoading: insightsLoading } = useQuery({
    queryKey: ["autopilot-learnings"],
    queryFn: () => getAutopilotLearnings(undefined, 50),
  });

  const anyRunning = extractMutation.isPending || titlesMutation.isPending || transcriptsMutation.isPending;

  return (
    <div className="p-4 md:p-8 max-w-[1200px] mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-display font-bold" style={{ color: "var(--text-primary)" }}>
            Learnings
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            Patterns discovered from your video performance and competitor analysis.
          </p>
        </div>
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
          <Brain size={14} />
          {learnings?.length ?? 0} patterns
        </div>
      </div>

      {/* Action Bar */}
      <GlassCard className="p-4">
        <div className="flex flex-wrap gap-3">
          <ActionBtn
            label="Extract Learnings"
            icon={<Sparkles size={14} />}
            color="var(--turquoise)"
            loading={extractMutation.isPending}
            onClick={() => extractMutation.mutate()}
            disabled={anyRunning}
          />
          <ActionBtn
            label="Analyze Titles"
            icon={<FileText size={14} />}
            color="var(--gold)"
            loading={titlesMutation.isPending}
            onClick={() => titlesMutation.mutate()}
            disabled={anyRunning}
          />
          <ActionBtn
            label="Analyze Transcripts"
            icon={<MessageSquare size={14} />}
            color="var(--purple)"
            loading={transcriptsMutation.isPending}
            onClick={() => transcriptsMutation.mutate()}
            disabled={anyRunning}
          />

          {/* Show result summary */}
          {extractMutation.data && (
            <span className="flex items-center gap-1 text-xs" style={{ color: "var(--green)" }}>
              Extracted {extractMutation.data.patterns_extracted} patterns from {extractMutation.data.videos_analyzed} videos
            </span>
          )}
          {titlesMutation.data && (
            <span className="flex items-center gap-1 text-xs" style={{ color: "var(--green)" }}>
              Found {titlesMutation.data.patterns_found} title patterns
            </span>
          )}
          {transcriptsMutation.data && (
            <span className="flex items-center gap-1 text-xs" style={{ color: "var(--green)" }}>
              Found {transcriptsMutation.data.patterns_found} hook patterns
            </span>
          )}
        </div>
      </GlassCard>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1 rounded-lg p-1" style={{ background: "rgba(255,255,255,0.03)" }}>
          {CATEGORIES.map((c) => (
            <button
              key={c.value}
              onClick={() => setCategory(c.value)}
              className="px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
              style={{
                background: category === c.value ? "rgba(0,212,170,0.15)" : "transparent",
                color: category === c.value ? "var(--turquoise)" : "var(--text-secondary)",
              }}
            >
              {c.label}
            </button>
          ))}
        </div>

        <button
          onClick={() => setShowInactive(!showInactive)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-colors"
          style={{
            background: showInactive ? "rgba(255,255,255,0.05)" : "transparent",
            color: "var(--text-secondary)",
          }}
        >
          {showInactive ? <ToggleRight size={14} style={{ color: "var(--turquoise)" }} /> : <ToggleLeft size={14} />}
          Show disabled
        </button>
      </div>

      {/* Pattern Cards */}
      {isLoading ? (
        <div className="flex justify-center py-16"><Spinner size="lg" /></div>
      ) : !learnings?.length ? (
        <EmptyState
          icon={Brain}
          title="No patterns found"
          description='Run "Extract Learnings" after publishing videos with performance data.'
          actionLabel="Extract Learnings"
          onAction={() => extractMutation.mutate()}
        />
      ) : (
        <motion.div
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
          variants={container}
          initial="hidden"
          animate="show"
        >
          {learnings.map((lr) => (
            <PatternCard
              key={lr.id}
              learning={lr}
              onToggle={() => toggleMutation.mutate(lr.id)}
              toggleLoading={toggleMutation.isPending}
            />
          ))}
        </motion.div>
      )}

      {/* Competitor Title Patterns */}
      <div className="space-y-3 pt-4">
        <h2 className="text-lg font-display font-bold" style={{ color: "var(--text-primary)" }}>
          Competitor Title Patterns
        </h2>
        <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
          Patterns discovered from competitor video titles and their performance.
        </p>

        {insightsLoading ? (
          <div className="flex justify-center py-8"><Spinner size="md" /></div>
        ) : !titleInsights?.length ? (
          <EmptyState
            icon={TrendingUp}
            title="No title insights yet"
            description='Run "Analyze Titles" to discover patterns.'
            actionLabel="Analyze Titles"
            onAction={() => titlesMutation.mutate()}
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {titleInsights.map((insight) => (
              <TitleInsightCard key={insight.id} insight={insight} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* --- Sub-components (inline, anti-bloat) --- */

function ActionBtn({
  label, icon, color, loading, onClick, disabled,
}: {
  label: string; icon: React.ReactNode; color: string;
  loading: boolean; onClick: () => void; disabled: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium transition-all disabled:opacity-40"
      style={{
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 25%, transparent)`,
      }}
    >
      {loading ? <Loader2 size={14} className="animate-spin" /> : icon}
      {label}
    </button>
  );
}

function PatternCard({
  learning, onToggle, toggleLoading,
}: {
  learning: LearningRecord; onToggle: () => void; toggleLoading: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const verdict = getVerdict(learning.confidence);
  const catColor = CATEGORY_COLORS[learning.category] || "var(--text-secondary)";

  // Parse source_videos JSON
  let sourceVideos: string[] = [];
  if (learning.source_videos) {
    try {
      const parsed = JSON.parse(learning.source_videos);
      sourceVideos = Array.isArray(parsed) ? parsed.slice(0, 10) : [];
    } catch {
      sourceVideos = [];
    }
  }

  return (
    <motion.div variants={item}>
      <GlassCard
        className="p-4 space-y-3"
        style={{ opacity: learning.active ? 1 : 0.5 }}
      >
        {/* Top row: category + verdict + toggle */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              className="text-[10px] uppercase tracking-wider font-mono px-2 py-0.5 rounded"
              style={{ background: `color-mix(in srgb, ${catColor} 15%, transparent)`, color: catColor }}
            >
              {learning.category}
            </span>
            <span
              className="text-[10px] uppercase tracking-wider font-mono px-2 py-0.5 rounded"
              style={{ background: `color-mix(in srgb, ${verdict.color} 15%, transparent)`, color: verdict.color }}
            >
              {verdict.label}
            </span>
          </div>
          <button
            onClick={onToggle}
            disabled={toggleLoading}
            className="transition-colors"
            title={learning.active ? "Disable pattern" : "Enable pattern"}
          >
            {learning.active
              ? <ToggleRight size={18} style={{ color: "var(--turquoise)" }} />
              : <ToggleLeft size={18} style={{ color: "var(--text-tertiary)" }} />}
          </button>
        </div>

        {/* Pattern text */}
        <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
          {learning.pattern}
        </p>

        {/* Confidence bar */}
        <div>
          <div className="flex justify-between text-[10px] mb-1" style={{ color: "var(--text-tertiary)" }}>
            <span>Confidence</span>
            <span style={{ color: verdict.color }}>{learning.confidence}%</span>
          </div>
          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${Math.min(100, learning.confidence)}%`, background: verdict.color }}
            />
          </div>
        </div>

        {/* Stats row */}
        <div className="flex gap-4 text-[10px]" style={{ color: "var(--text-secondary)" }}>
          <span>n={learning.sample_size}</span>
          {learning.avg_ctr != null && (
            <span>
              CTR <span style={{ color: learning.avg_ctr >= 5 ? "var(--green)" : learning.avg_ctr >= 3.5 ? "var(--gold)" : "var(--red)" }}>
                {learning.avg_ctr.toFixed(1)}%
              </span>
            </span>
          )}
          {learning.avg_retention != null && (
            <span>Retention {learning.avg_retention.toFixed(1)}%</span>
          )}
        </div>

        {/* Source videos (expandable) */}
        {sourceVideos.length > 0 && (
          <div>
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-[10px] transition-colors"
              style={{ color: "var(--text-tertiary)" }}
            >
              <ChevronDown
                size={12}
                style={{ transform: expanded ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s" }}
              />
              {sourceVideos.length} source video{sourceVideos.length !== 1 ? "s" : ""}
            </button>
            {expanded && (
              <div className="flex flex-wrap gap-1 mt-2">
                {sourceVideos.map((v, i) => (
                  <span
                    key={i}
                    className="text-[10px] px-2 py-0.5 rounded"
                    style={{ background: "rgba(255,255,255,0.04)", color: "var(--text-secondary)" }}
                  >
                    {v}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </GlassCard>
    </motion.div>
  );
}

function TitleInsightCard({ insight }: { insight: Learning }) {
  const confColor = insight.confidence >= 60 ? "var(--green)" : insight.confidence >= 40 ? "var(--gold)" : "var(--red)";

  return (
    <GlassCard className="p-4 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
          {insight.pattern}
        </p>
        {insight.avg_ctr != null && (
          <span
            className="text-[10px] font-mono px-2 py-0.5 rounded shrink-0"
            style={{
              background: `color-mix(in srgb, ${insight.avg_ctr >= 5 ? "var(--green)" : insight.avg_ctr >= 3.5 ? "var(--gold)" : "var(--red)"} 15%, transparent)`,
              color: insight.avg_ctr >= 5 ? "var(--green)" : insight.avg_ctr >= 3.5 ? "var(--gold)" : "var(--red)",
            }}
          >
            {insight.avg_ctr.toFixed(1)}% CTR
          </span>
        )}
      </div>

      {/* Confidence bar */}
      <div>
        <div className="flex justify-between text-[10px] mb-1" style={{ color: "var(--text-tertiary)" }}>
          <span>n={insight.sample_size}</span>
          <span style={{ color: confColor }}>{insight.confidence}%</span>
        </div>
        <div className="h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
          <div
            className="h-full rounded-full transition-all"
            style={{ width: `${Math.min(100, insight.confidence)}%`, background: confColor }}
          />
        </div>
      </div>

      {/* Effect / category */}
      <div className="flex gap-3 text-[10px]" style={{ color: "var(--text-secondary)" }}>
        {insight.effect && <span>{insight.effect}</span>}
        <span
          className="uppercase tracking-wider font-mono px-1.5 py-0.5 rounded"
          style={{ background: `color-mix(in srgb, ${CATEGORY_COLORS[insight.category] || "var(--text-secondary)"} 15%, transparent)`, color: CATEGORY_COLORS[insight.category] || "var(--text-secondary)" }}
        >
          {insight.category}
        </span>
      </div>
    </GlassCard>
  );
}
