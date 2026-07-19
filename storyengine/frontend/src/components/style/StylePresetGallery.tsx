"use client";

// The "Look Engine" gallery (checklist §2.1 [U], C21a) — sourced from
// GET /api/style-presets via the shared useStylePresets() hook (one fetcher,
// one ["style-presets"] query key, reused by the chat LOOK card in C21b).
//
// This is the STRUCTURAL engine axis (style_preset_id -> VISUAL_PROFILE),
// NOT the free-text "look" description axis (image_style_override /
// visual_style_label) that the New Video page's existing "Visual style"
// section already writes — the two are independent and complementary (see
// docs/reports/2026-07-17-storyengine-agent-audit-findings.md §S9-5 and
// SYSTEM_STATE.md §C20/§C21a). A creator may pick an engine here AND still
// type a custom look below; neither clobbers the other.
import { useState } from "react";
import { Loader2, AlertTriangle, Sparkles } from "lucide-react";
import type { StylePreset } from "@/lib/api";
import { useStylePresets } from "@/hooks/use-style-presets";

const COST_TIER_LABEL: Record<string, string> = { low: "$", mid: "$$", high: "$$$" };

// No python_profile preset ships a generated preview image yet (preview_url
// is NULL for all 5 seeded rows), so "no url" is the NORMAL case, not a
// broken state — render a labeled placeholder instead of pointing an <img>
// at nothing. A future preview_url that 404s falls back the same way
// (S9-4 standard: never a broken-image icon, matching SceneBoardsGrid's
// onError -> label pattern from C15b).
function EngineCardImage({ preset }: { preset: StylePreset }) {
  const [broken, setBroken] = useState(false);
  if (!preset.preview_url || broken) {
    return (
      <div
        className="w-full h-14 rounded-lg flex items-center justify-center"
        style={{ background: "var(--bg-surface)" }}
      >
        <Sparkles size={18} style={{ color: "var(--text-tertiary)" }} />
      </div>
    );
  }
  return (
    <img
      src={preset.preview_url}
      alt={preset.display_name}
      onError={() => setBroken(true)}
      className="w-full h-14 rounded-lg object-cover"
      style={{ background: "var(--bg-surface)" }}
    />
  );
}

export function StylePresetGallery({
  selectedId,
  onSelect,
}: {
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const { data, isLoading, error, refetch } = useStylePresets();
  const presets = data?.presets ?? [];

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs py-3" style={{ color: "var(--text-tertiary)" }}>
        <Loader2 size={12} className="animate-spin" /> Loading look engines…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="flex items-center justify-between gap-2 text-xs py-2 px-3 rounded-lg"
        style={{ background: "var(--red-dim)", color: "var(--red)" }}
      >
        <span className="flex items-center gap-1.5">
          <AlertTriangle size={12} /> Couldn&apos;t load look engines.
        </span>
        <button type="button" onClick={() => refetch()} className="underline font-medium">
          Retry
        </button>
      </div>
    );
  }
  if (presets.length === 0) {
    // Fail-soft empty state — a creator can still finish the form; the
    // executor's own fail-soft chain (_resolve_visual_profile_id) falls back
    // to neutral_v1 when no style_preset_id is sent.
    return (
      <p className="text-[11px] py-2" style={{ color: "var(--text-tertiary)" }}>
        No look engines available right now — your channel&apos;s default will be used.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
      {presets.map((p) => {
        const active = selectedId === p.id;
        return (
          <button
            key={p.id}
            type="button"
            onClick={() => onSelect(active ? "" : p.id)}
            title={p.description ?? undefined}
            className="flex flex-col gap-1.5 p-2 rounded-lg text-left transition-all active:scale-[0.98]"
            style={{
              background: active ? "rgba(0,212,170,0.1)" : "var(--bg-elevated)",
              border: `1px solid ${active ? "var(--turquoise)" : "var(--border)"}`,
            }}
          >
            <EngineCardImage preset={p} />
            <span
              className="text-xs font-medium"
              style={{ color: active ? "var(--turquoise)" : "var(--text-primary)" }}
            >
              {p.display_name}
            </span>
            {p.best_for.length > 0 && (
              <span className="text-[10px] leading-snug" style={{ color: "var(--text-tertiary)" }}>
                Best for {p.best_for.slice(0, 2).join(", ")}
              </span>
            )}
            {p.cost_tier && (
              <span className="text-[9px] font-mono uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>
                {COST_TIER_LABEL[p.cost_tier] ?? p.cost_tier} cost
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
