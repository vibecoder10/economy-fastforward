"use client";

import { useMemo, useState, useCallback } from "react";
import { RefreshCw, FileText, Search, Loader2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { runPipelineStage } from "@/lib/api";

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

  const handleReResearch = useCallback(async () => {
    setIsResearching(true);
    try {
      await runPipelineStage(video.id, "research");
    } finally {
      setIsResearching(false);
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
          Deep research will analyze the topic and generate a comprehensive payload for scripting.
        </p>
        <ActionButton variant="filled" icon={RefreshCw}>
          Run Research
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
      <div className="flex gap-3 justify-end">
        <ActionButton variant="outline" icon={RefreshCw}>Re-research</ActionButton>
        <ActionButton variant="outline" icon={FileText}>Export to Google Docs</ActionButton>
      </div>
    </div>
  );
}
