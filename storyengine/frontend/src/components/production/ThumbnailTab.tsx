"use client";

import { useState, useCallback } from "react";
import { Check, RefreshCw, Loader2, ChevronDown, ChevronUp } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { runPipelineStage, advanceVideo, updateVideoStyles } from "@/lib/api";
import type { VideoDetail } from "@/lib/api";

const ACCENT_COLORS = [
  { name: "Cold Teal", value: "#4A9E9E" },
  { name: "Muted Crimson", value: "#A63D40" },
  { name: "Warm Amber", value: "#C4923A" },
  { name: "Muted Green", value: "#5E8C61" },
] as const;

interface ThumbnailTabProps {
  video: VideoDetail & {
    id: string;
    title?: string;
    thumbnailUrl?: string | null;
  };
}

export function ThumbnailTab({ video }: ThumbnailTabProps) {
  const currentAccent = video.accent_color || "Cold Teal";
  const [selectedAccent, setSelectedAccent] = useState(currentAccent);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isApproved, setIsApproved] = useState(false);
  const [isSavingColor, setIsSavingColor] = useState(false);
  const [prompt, setPrompt] = useState(video.thumbnail_prompt || "");
  const [promptExpanded, setPromptExpanded] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const vid = video as any;
  const [thumbnailText, setThumbnailText] = useState(
    vid.video_title || video.title || "",
  );

  const handleRegenerate = useCallback(async () => {
    setIsRegenerating(true);
    setIsApproved(false);
    try {
      await runPipelineStage(video.id, "thumbnail");
    } finally {
      setIsRegenerating(false);
    }
  }, [video.id]);

  const handleApprove = useCallback(async () => {
    setIsApproving(true);
    try {
      await advanceVideo(video.id);
      setIsApproved(true);
    } catch {
      // silent
    } finally {
      setIsApproving(false);
    }
  }, [video.id]);

  const handleAccentChange = useCallback(async (colorName: string) => {
    setSelectedAccent(colorName);
    setIsSavingColor(true);
    try {
      await updateVideoStyles(video.id, {
        accent_color: colorName.toLowerCase().replace(" ", "_"),
      });
    } finally {
      setIsSavingColor(false);
    }
  }, [video.id]);

  const thumbnailUrl = video.thumbnail_url || vid.thumbnailUrl;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      {/* Main content */}
      <div className="space-y-4">
        {/* Video title */}
        <div>
          <h2
            className="text-xl font-display"
            style={{ color: "var(--text-primary)" }}
          >
            {vid.video_title || video.title || "Untitled"}
          </h2>
        </div>

        {/* 16:9 thumbnail preview */}
        <GlassCard className="p-0 overflow-hidden">
          <div
            className="aspect-video relative flex items-center justify-center"
            style={{ background: "var(--bg-elevated)" }}
          >
            {thumbnailUrl ? (
              <img
                src={thumbnailUrl}
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

        {/* Prompt (collapsible, editable) */}
        <GlassCard
          className="p-4"
          style={{ borderLeftWidth: 3, borderLeftColor: "var(--gold)" }}
        >
          <button
            className="w-full flex items-center justify-between"
            onClick={() => setPromptExpanded(!promptExpanded)}
          >
            <h3
              className="text-xs font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-secondary)" }}
            >
              Thumbnail Prompt
            </h3>
            {promptExpanded ? (
              <ChevronUp size={14} style={{ color: "var(--text-tertiary)" }} />
            ) : (
              <ChevronDown size={14} style={{ color: "var(--text-tertiary)" }} />
            )}
          </button>
          {promptExpanded && (
            <div className="mt-3">
              {prompt ? (
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={4}
                  className="w-full text-sm leading-relaxed bg-transparent outline-none resize-none rounded-lg px-2 py-1 transition-all"
                  style={{
                    color: "var(--text-primary)",
                    border: "1px solid var(--border-subtle)",
                  }}
                  onFocus={(e) => { e.target.style.borderColor = "var(--gold)"; }}
                  onBlur={(e) => { e.target.style.borderColor = "var(--border-subtle)"; }}
                />
              ) : (
                <p className="text-sm italic" style={{ color: "var(--text-tertiary)" }}>
                  No prompt generated yet. Run the thumbnail stage to generate one.
                </p>
              )}
            </div>
          )}
        </GlassCard>
      </div>

      {/* Sidebar */}
      <div className="space-y-4">
        {/* Accent Color */}
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
                onClick={() => handleAccentChange(c.name)}
                disabled={isSavingColor}
                className="flex items-center gap-2 px-2 py-1.5 rounded-lg transition-all text-left"
                style={{
                  background: selectedAccent === c.name ? `${c.value}22` : "transparent",
                  border: `1px solid ${selectedAccent === c.name ? c.value : "var(--border-subtle)"}`,
                }}
              >
                <span
                  className="w-4 h-4 rounded-full flex-shrink-0"
                  style={{ background: c.value }}
                />
                <span
                  className="text-[10px] font-medium"
                  style={{ color: selectedAccent === c.name ? c.value : "var(--text-secondary)" }}
                >
                  {c.name}
                </span>
              </button>
            ))}
          </div>
        </GlassCard>

        {/* Thumbnail Text */}
        <GlassCard className="p-5">
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-2"
            style={{ color: "var(--text-secondary)" }}
          >
            Thumbnail Text
          </h3>
          <input
            type="text"
            value={thumbnailText}
            onChange={(e) => setThumbnailText(e.target.value)}
            className="w-full px-3 py-2 rounded-lg text-sm font-body outline-none transition-all"
            style={{
              background: "var(--bg-elevated)",
              color: "var(--text-primary)",
              border: "1px solid var(--border)",
            }}
            onFocus={(e) => { e.target.style.borderColor = "var(--turquoise)"; }}
            onBlur={(e) => { e.target.style.borderColor = "var(--border)"; }}
          />
        </GlassCard>

        {/* Actions */}
        <div className="space-y-2">
          <ActionButton
            variant="filled"
            icon={isApproving ? Loader2 : isApproved ? Check : undefined}
            className="w-full"
            onClick={handleApprove}
            disabled={isApproving || isApproved}
          >
            {isApproving
              ? "Approving..."
              : isApproved
                ? "Approved"
                : "Approve Thumbnail"}
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
        </div>
      </div>
    </div>
  );
}
