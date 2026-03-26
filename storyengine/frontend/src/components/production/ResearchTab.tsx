"use client";

import { useMemo, useState, useCallback } from "react";
import { RefreshCw, FileText, Search, Loader2, Check } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { runPipelineStage, advanceVideo } from "@/lib/api";

interface ResearchTabProps {
  video: any;
}

interface FieldDef {
  key: string;
  label: string;
  fullWidth: boolean;
  borderColor?: string;
  mono?: boolean;
}

const FIELDS: FieldDef[] = [
  { key: "thesis", label: "Thesis", fullWidth: true, borderColor: "var(--turquoise)" },
  { key: "executive_hook", label: "Executive Hook", fullWidth: true, borderColor: "var(--orange)" },
  { key: "fact_sheet", label: "Fact Sheet", fullWidth: false },
  { key: "historical_parallels", label: "Historical Parallels", fullWidth: false },
  { key: "framework_analysis", label: "Framework Analysis", fullWidth: false },
  { key: "character_dossier", label: "Character Dossier", fullWidth: false },
  { key: "narrative_arc", label: "Narrative Arc", fullWidth: true },
  { key: "counter_arguments", label: "Counter Arguments", fullWidth: false },
  { key: "visual_seeds", label: "Visual Seeds", fullWidth: false },
  { key: "themes", label: "Themes", fullWidth: false },
  { key: "psychological_angles", label: "Psychological Angles", fullWidth: false },
  { key: "source_bibliography", label: "Sources", fullWidth: true, mono: true },
];

export function ResearchTab({ video }: ResearchTabProps) {
  const [isResearching, setIsResearching] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackSaved, setFeedbackSaved] = useState(false);

  const handleReResearch = useCallback(async () => {
    setIsResearching(true);
    try {
      await runPipelineStage(video.id, "research");
    } finally {
      setIsResearching(false);
    }
  }, [video.id]);

  const handleApproveResearch = useCallback(async () => {
    if (!confirm("Approve research and move to scripting?")) return;
    setIsApproving(true);
    try {
      await advanceVideo(video.id);
    } catch (err) {
      alert(`Failed: ${(err as Error).message}`);
    } finally {
      setIsApproving(false);
    }
  }, [video.id]);

  // Parse research_payload from the video detail
  const research = useMemo(() => {
    if (!video) return null;

    // Try parsing research_payload JSON
    let payload: Record<string, string> = {};
    if (video.research_payload) {
      try {
        payload = typeof video.research_payload === "string"
          ? JSON.parse(video.research_payload)
          : video.research_payload;
      } catch {
        payload = {};
      }
    }

    // Merge top-level fields (fallback to payload values)
    return {
      headline: video.headline || payload.headline || null,
      thesis: video.thesis || payload.thesis || null,
      executive_hook: video.executive_hook || payload.executive_hook || null,
      fact_sheet: payload.fact_sheet || null,
      historical_parallels: payload.historical_parallels || null,
      framework_analysis: payload.framework_analysis || null,
      character_dossier: payload.character_dossier || null,
      narrative_arc: payload.narrative_arc || payload.narrative_arc_suggestion || null,
      counter_arguments: payload.counter_arguments || null,
      visual_seeds: payload.visual_seeds || null,
      themes: payload.themes || null,
      psychological_angles: payload.psychological_angles || null,
      source_bibliography: payload.source_bibliography || null,
    };
  }, [video]);

  if (!research || !research.headline) {
    return (
      <GlassCard className="p-12 text-center">
        <Search size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          Research Not Started
        </p>
        <p className="text-sm mb-6" style={{ color: "var(--text-tertiary)" }}>
          Research not started yet. This video is at the &ldquo;{video.status?.replace(/_/g, " ") || "idea logged"}&rdquo; stage.
        </p>
        <ActionButton
          variant="filled"
          icon={isResearching ? Loader2 : RefreshCw}
          onClick={handleReResearch}
          disabled={isResearching}
        >
          {isResearching ? "Researching..." : "Run Research"}
        </ActionButton>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-4">
      {/* Headline */}
      <GlassCard className="p-5" style={{ borderLeftWidth: 3, borderLeftColor: "var(--gold)" }}>
        <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
          Headline
        </h3>
        <textarea
          defaultValue={research.headline}
          rows={2}
          className="w-full text-lg font-semibold resize-none outline-none rounded-lg px-2 py-1 transition-all"
          style={{ color: "var(--text-primary)", background: "transparent", border: "1px solid transparent" }}
          onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--gold)"; }}
          onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
        />
      </GlassCard>

      {/* Research fields */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {FIELDS.map((field) => {
          const content = research[field.key as keyof typeof research];
          if (!content) return null;

          return (
            <GlassCard
              key={field.key}
              className={`p-5 ${field.fullWidth ? "lg:col-span-2" : ""}`}
              style={field.borderColor ? { borderLeftWidth: 3, borderLeftColor: field.borderColor } : undefined}
            >
              <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-tertiary)" }}>
                {field.label}
              </h3>
              <textarea
                defaultValue={content}
                rows={Math.max(3, Math.ceil(content.length / 100))}
                className={`w-full text-sm leading-relaxed whitespace-pre-line resize-none outline-none rounded-lg px-2 py-1 transition-all ${field.mono ? "font-mono text-xs" : ""}`}
                style={{ color: "var(--text-primary)", background: "transparent", border: "1px solid transparent" }}
                onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--turquoise)"; }}
                onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
              />
            </GlassCard>
          );
        })}
      </div>

      {/* Actions */}
      <div className="flex gap-3 justify-end flex-wrap">
        <button
          className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
          style={{
            background: "rgba(255, 120, 73, 0.15)",
            color: "var(--orange)",
            border: "1px solid var(--orange)",
          }}
          onClick={handleReResearch}
          disabled={isResearching}
        >
          {isResearching ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          {isResearching ? "Researching..." : "Regenerate Research"}
        </button>
        <button
          className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98]"
          style={{
            background: "transparent",
            color: "var(--text-secondary)",
            border: "1px solid var(--border)",
          }}
          onClick={() => setShowFeedback(true)}
        >
          <FileText size={16} /> Request Changes
        </button>
        <button
          className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
          style={{ background: "var(--green)", color: "var(--bg-void)" }}
          onClick={handleApproveResearch}
          disabled={isApproving}
        >
          {isApproving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
          {isApproving ? "Approving..." : "Approve Research"}
        </button>
      </div>

      {/* Feedback Modal */}
      {showFeedback && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setShowFeedback(false)}>
          <div className="w-full max-w-md rounded-xl p-6 space-y-4" style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }} onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Request Changes</h3>
            <textarea
              value={feedbackText}
              onChange={(e) => setFeedbackText(e.target.value)}
              placeholder="What should be changed?"
              rows={4}
              className="w-full px-3 py-2 rounded-lg text-sm outline-none resize-none"
              style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              autoFocus
            />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowFeedback(false)} className="px-4 py-2 rounded-lg text-sm" style={{ color: "var(--text-secondary)" }}>Cancel</button>
              <button
                onClick={() => { console.log("Research feedback:", feedbackText); setShowFeedback(false); setFeedbackSaved(true); setTimeout(() => setFeedbackSaved(false), 2000); }}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
              >
                Save Feedback
              </button>
            </div>
          </div>
        </div>
      )}

      {feedbackSaved && (
        <div className="text-sm text-center py-2" style={{ color: "var(--green)" }}>Feedback saved</div>
      )}
    </div>
  );
}
