"use client";

import { useState } from "react";
import { Check, RefreshCw, PenLine } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import type { Video } from "@/lib/types";

const ACCENT_COLORS = [
  { name: "Cold Teal", value: "#4A9E9E" },
  { name: "Muted Crimson", value: "#A63D40" },
  { name: "Warm Amber", value: "#C4923A" },
  { name: "Muted Green", value: "#5E8C61" },
] as const;

const MOCK_THUMBNAIL = {
  prompt:
    "Stern leader portrait on deep red gradient, yellow bold text overlay, editorial illustration, high saturation",
  accentColor: "Cold Teal",
  styleOverride: "REPLACE: Red gradient background transitioning from deep crimson top to darker red bottom.",
  thumbnailText: "THE $3 TRILLION TRAP",
};

interface ThumbnailTabProps {
  video: Video;
}

export function ThumbnailTab({ video }: ThumbnailTabProps) {
  const [selectedAccent, setSelectedAccent] = useState(MOCK_THUMBNAIL.accentColor);

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
                    Thumbnail not generated yet
                  </p>
                </div>
              </>
            )}
          </div>
        </GlassCard>

        {/* Prompt display */}
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
          <p className="text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>
            {MOCK_THUMBNAIL.prompt}
          </p>
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
            {[
              { label: "Accent Color", value: selectedAccent },
              { label: "Thumbnail Text", value: MOCK_THUMBNAIL.thumbnailText },
            ].map((row) => (
              <div key={row.label}>
                <span
                  className="text-[10px] font-medium uppercase tracking-wider block mb-1"
                  style={{ color: "var(--text-tertiary)" }}
                >
                  {row.label}
                </span>
                <span
                  className="text-sm font-mono"
                  style={{ color: "var(--text-primary)" }}
                >
                  {row.value}
                </span>
              </div>
            ))}

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
                {MOCK_THUMBNAIL.styleOverride}
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
          <ActionButton variant="outline" icon={RefreshCw} className="w-full">
            Regenerate
          </ActionButton>
          <ActionButton variant="outline" icon={PenLine} className="w-full">
            Edit Text
          </ActionButton>
        </div>
      </div>
    </div>
  );
}
