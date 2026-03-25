"use client";

import { useState } from "react";
import { Check, RefreshCw, PenLine, Loader2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { runPipelineStage } from "@/lib/api";
import type { Video } from "@/lib/types";

const ACCENT_COLORS = [
  { name: "Cold Teal", value: "#4A9E9E" },
  { name: "Muted Crimson", value: "#A63D40" },
  { name: "Warm Amber", value: "#C4923A" },
  { name: "Muted Green", value: "#5E8C61" },
] as const;

interface ThumbnailTabProps {
  video: Video & {
    thumbnail_prompt?: string | null;
    thumbnail_style_override?: string | null;
    accent_color?: string | null;
  };
}

export function ThumbnailTab({ video }: ThumbnailTabProps) {
  const currentAccent = video.accent_color || "Cold Teal";
  const [selectedAccent, setSelectedAccent] = useState(currentAccent);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [prompt, setPrompt] = useState(video.thumbnail_prompt || "");

  const handleRegenerate = async () => {
    setIsRegenerating(true);
    try {
      await runPipelineStage(video.id, "thumbnail");
    } finally {
      setIsRegenerating(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      {/* Main content */}
      <div className="space-y-4">
        {/* 16:9 thumbnail preview */}
        <GlassCard className="p-0 overflow-hidden">
          <div
            className="aspect-video relative flex items-center justify-center"
            style={{ background: "var(--bg-elevated)" }}
          >
            {video.thumbnailUrl ? (
              <img
                src={video.thumbnailUrl}
                alt="Thumbnail preview"
                className="w-full h-full object-cover"
              />
            ) : (
              <>
                <svg className="absolute inset-0 w-full h-full opacity-10">
                  <defs>
                    <pattern
                      id="thumb-holo-grid"
                      width="40"
                      height="40"
                      patternUnits="userSpaceOnUse"
                    >
                      <path
                        d="M 40 0 L 0 0 0 40"
                        fill="none"
                        stroke="var(--turquoise)"
                        strokeWidth="0.5"
                      />
                    </pattern>
                  </defs>
                  <rect width="100%" height="100%" fill="url(#thumb-holo-grid)" />
                </svg>
                <div className="text-center z-10">
                  <div
                    className="w-16 h-16 rounded-xl mx-auto mb-3 flex items-center justify-center"
                    style={{ background: "var(--turquoise-dim)" }}
                  >
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
                      <rect x="3" y="3" width="18" height="13" rx="2" stroke="var(--turquoise)" strokeWidth="1.5" />
                      <path d="M8 20h8" stroke="var(--turquoise)" strokeWidth="1.5" strokeLinecap="round" />
                      <path d="M12 16v4" stroke="var(--turquoise)" strokeWidth="1.5" />
                    </svg>
                  </div>
                  <p className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                    Not generated yet
                  </p>
                </div>
              </>
            )}
          </div>
        </GlassCard>

        {/* Prompt display (editable) */}
        <GlassCard
          className="p-4"
          style={{ borderLeftWidth: 3, borderLeftColor: "var(--gold)" }}
        >
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-2"
            style={{ color: "var(--text-secondary)" }}
          >
            Thumbnail Prompt
          </h3>
          {prompt ? (
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              className="w-full text-sm leading-relaxed bg-transparent outline-none resize-none"
              style={{ color: "var(--text-primary)" }}
            />
          ) : (
            <p className="text-sm italic" style={{ color: "var(--text-tertiary)" }}>
              No prompt generated yet. Run the thumbnail stage to generate one.
            </p>
          )}
        </GlassCard>
      </div>

      {/* Sidebar */}
      <div className="space-y-4">
        <GlassCard className="p-5">
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-3"
            style={{ color: "var(--text-secondary)" }}
          >
            Thumbnail Details
          </h3>
          <div className="space-y-3">
            <div>
              <span
                className="text-[10px] font-medium uppercase tracking-wider block mb-1"
                style={{ color: "var(--text-tertiary)" }}
              >
                Accent Color
              </span>
              <span
                className="text-sm font-mono"
                style={{ color: "var(--text-primary)" }}
              >
                {selectedAccent}
              </span>
            </div>

            <div>
              <span
                className="text-[10px] font-medium uppercase tracking-wider block mb-1"
                style={{ color: "var(--text-tertiary)" }}
              >
                Style Override
              </span>
              <p
                className="text-[11px] font-mono leading-relaxed"
                style={{ color: "var(--text-secondary)" }}
              >
                {video.thumbnail_style_override || "None"}
              </p>
            </div>
          </div>
        </GlassCard>

        {/* Color swatches */}
        <GlassCard className="p-5">
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-3"
            style={{ color: "var(--text-secondary)" }}
          >
            Accent Color
          </h3>
          <div className="grid grid-cols-2 gap-2">
            {ACCENT_COLORS.map((c) => (
              <button
                key={c.name}
                onClick={() => setSelectedAccent(c.name)}
                className="flex items-center gap-2 px-2 py-1.5 rounded-lg transition-all text-left"
                style={{
                  background:
                    selectedAccent === c.name ? `${c.value}22` : "transparent",
                  border: `1px solid ${selectedAccent === c.name ? c.value : "var(--border-subtle)"}`,
                }}
              >
                <span
                  className="w-4 h-4 rounded-full flex-shrink-0"
                  style={{ background: c.value }}
                />
                <span
                  className="text-[10px] font-medium"
                  style={{
                    color: selectedAccent === c.name ? c.value : "var(--text-secondary)",
                  }}
                >
                  {c.name}
                </span>
              </button>
            ))}
          </div>
        </GlassCard>

        <div className="space-y-2">
          <ActionButton variant="filled" icon={Check} className="w-full">
            Approve Thumbnail
          </ActionButton>
          <ActionButton
            variant="outline"
            icon={isRegenerating ? Loader2 : RefreshCw}
            className="w-full"
            onClick={handleRegenerate}
            disabled={isRegenerating}
          >
            {isRegenerating ? "Regenerating..." : "Regenerate"}
          </ActionButton>
          <ActionButton variant="outline" icon={PenLine} className="w-full">
            Edit Text
          </ActionButton>
        </div>
      </div>
    </div>
  );
}
