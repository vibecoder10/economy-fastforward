"use client";

import { useQuery } from "@tanstack/react-query";
import {
  BookOpenText,
  Languages,
  Loader2,
  PanelsTopLeft,
  SearchCheck,
  TriangleAlert,
} from "lucide-react";
import {
  getProductionStyles,
  type ProductionStyle,
  type ProductionStyleId,
} from "@/lib/api";
import { DriveStorageNotice } from "@/components/storage/DriveStorageNotice";
import { cn } from "@/lib/utils";

const STYLE_ICON = {
  bilingual_character_animation: Languages,
  simple_language_animation: BookOpenText,
  photo_documentary: PanelsTopLeft,
  animated_investigative_documentary: SearchCheck,
} satisfies Record<ProductionStyleId, typeof Languages>;

function mediaEstimate(style: ProductionStyle, durationMinutes: number): string {
  const estimate = style.estimate;
  if (
    estimate.image_count_mode === "duration"
    && typeof estimate.images_per_minute === "number"
  ) {
    const images = Math.max(1, Math.round(estimate.images_per_minute * durationMinutes));
    const clipsPerImage = estimate.clips_per_image ?? 0;
    const clips = Math.max(0, Math.round(images * clipsPerImage));
    return clips > 0
      ? `About ${images} generated images + ${clips} animated clips`
      : `About ${images} generated images`;
  }
  if (
    estimate.image_count_mode === "per_item"
    && typeof estimate.images_per_item === "number"
  ) {
    const stills = estimate.images_per_item;
    return `${stills} generated stills per item · no generated animation clips`;
  }
  return estimate.copy || "Media use depends on the final script.";
}

export function ProductionStyleSelector({
  selectedId,
  onSelect,
  durationMinutes,
  className,
}: {
  selectedId: ProductionStyleId | "";
  onSelect: (styleId: ProductionStyleId) => void;
  durationMinutes: number;
  className?: string;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["production-styles"],
    queryFn: getProductionStyles,
    staleTime: 5 * 60 * 1000,
  });
  const styles = data?.styles ?? [];

  return (
    <fieldset className={cn("space-y-3", className)}>
      <legend
        className="text-sm font-body font-semibold"
        style={{ color: "var(--text-primary)" }}
      >
        Choose how StoryEngine should make this video{" "}
        <span style={{ color: "var(--red)" }}>*</span>
      </legend>
      <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
        Required. Nothing is preselected because this choice changes the script,
        pictures, voices, and motion—not just the visual look.
      </p>

      {isLoading && (
        <div
          className="flex items-center justify-center gap-2 rounded-lg px-3 py-5 text-xs"
          style={{ background: "var(--bg-elevated)", color: "var(--text-tertiary)" }}
        >
          <Loader2 size={14} className="animate-spin" />
          Loading video styles…
        </div>
      )}

      {isError && (
        <div
          role="alert"
          className="rounded-lg px-3 py-3 text-xs"
          style={{
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.3)",
            color: "var(--red)",
          }}
        >
          Video styles could not be loaded. Close this screen and try again.
        </div>
      )}

      {!isLoading && !isError && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {styles.map((style) => {
            const selected = selectedId === style.id;
            const Icon = STYLE_ICON[style.id];
            return (
              <button
                key={style.id}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => onSelect(style.id)}
                className="min-h-[154px] rounded-xl p-3 text-left transition-all"
                style={{
                  background: selected ? "rgba(0,212,170,0.09)" : "var(--bg-elevated)",
                  border: `1px solid ${selected ? "var(--turquoise)" : "var(--border)"}`,
                  boxShadow: selected ? "0 0 0 1px rgba(0,212,170,0.16)" : "none",
                }}
              >
                <div className="flex items-start justify-between gap-2">
                  <span
                    className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                    style={{
                      background: selected ? "rgba(0,212,170,0.16)" : "var(--surface)",
                      color: selected ? "var(--turquoise)" : "var(--text-tertiary)",
                    }}
                  >
                    <Icon size={16} />
                  </span>
                  <span
                    aria-hidden
                    className="w-4 h-4 rounded-full shrink-0 mt-0.5"
                    style={{
                      border: `2px solid ${selected ? "var(--turquoise)" : "var(--border)"}`,
                      background: selected ? "var(--turquoise)" : "transparent",
                      boxShadow: selected ? "inset 0 0 0 3px var(--bg-elevated)" : "none",
                    }}
                  />
                </div>
                <div className="mt-2.5 text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
                  {style.label}
                </div>
                <p className="text-[10px] leading-relaxed mt-1" style={{ color: "var(--text-secondary)" }}>
                  {style.description}
                </p>
                <p
                  className="text-[10px] leading-relaxed mt-2 font-medium"
                  style={{ color: selected ? "var(--turquoise)" : "var(--text-tertiary)" }}
                >
                  {mediaEstimate(style, durationMinutes)}
                </p>
              </button>
            );
          })}
        </div>
      )}

      <div
        className="flex items-start gap-2 rounded-lg px-3 py-2.5"
        style={{
          background: "rgba(245,158,11,0.07)",
          border: "1px solid rgba(245,158,11,0.22)",
        }}
      >
        <TriangleAlert size={14} className="shrink-0 mt-0.5" style={{ color: "var(--gold)" }} />
        <p className="text-[10px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          <strong style={{ color: "var(--text-primary)" }}>Bring your own provider keys.</strong>{" "}
          Image, voice, and video providers charge your accounts directly. StoryEngine
          shows a quote and asks you to confirm before paid generation.
        </p>
      </div>

      <DriveStorageNotice compact />

      {!selectedId && !isLoading && !isError && (
        <p className="text-[10px]" style={{ color: "var(--gold)" }}>
          Choose one video style to continue.
        </p>
      )}
    </fieldset>
  );
}
