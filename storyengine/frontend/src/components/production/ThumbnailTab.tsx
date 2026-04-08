"use client";

import { useState, useCallback, useRef } from "react";
import { Check, RefreshCw, Loader2, ChevronDown, ChevronUp, ChevronRight, Sparkles, X, ImageIcon, Save } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { useQueryClient } from "@tanstack/react-query";
import { runPipelineStage, advanceVideo, updateVideoStyles, updateVideo, clearStaleTask, acceptSuggestion, rejectSuggestion, getDefaultThumbnailPrompt } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { SystemPromptEditor } from "@/components/ui/SystemPromptEditor";
import type { VideoDetail } from "@/lib/api";
import { getStageIndex } from "@/lib/constants";

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
  onAdvanced?: () => void;
}

export function ThumbnailTab({ video, onAdvanced }: ThumbnailTabProps) {
  const queryClient = useQueryClient();
  const currentAccent = video.accent_color || "Cold Teal";
  const [selectedAccent, setSelectedAccent] = useState(currentAccent);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isApproved, setIsApproved] = useState(false);
  const [isSavingColor, setIsSavingColor] = useState(false);
  const [prompt, setPrompt] = useState(video.thumbnail_prompt || "");
  const [promptExpanded, setPromptExpanded] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);
  const [isSavingPrompt, setIsSavingPrompt] = useState(false);
  const [promptSaved, setPromptSaved] = useState(false);
  const savedPromptRef = useRef(video.thumbnail_prompt || "");

  // Thumbnail generation requires the video to be at or past ready_for_thumbnail
  const thumbnailStageIdx = getStageIndex("ready_for_thumbnail");
  const currentStageIdx = getStageIndex(video.status || "");
  const isReadyForThumbnail = currentStageIdx >= thumbnailStageIdx;

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: taskRunning,
    interval: 3000,
    onComplete: () => {
      setTaskRunning(false);
      setIsRegenerating(false);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setIsRegenerating(false);
      alert(`Thumbnail generation failed: ${error}`);
    },
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const vid = video as any;
  const [thumbnailText, setThumbnailText] = useState(
    vid.video_title || video.title || "",
  );
  const [isAccepting, setIsAccepting] = useState(false);
  const [isRejecting, setIsRejecting] = useState(false);
  const [suggestionDismissed, setSuggestionDismissed] = useState(false);

  const hasSuggestions =
    !suggestionDismissed &&
    video.suggested_thumbnail_urls &&
    video.suggested_thumbnail_urls.length > 0;

  const handleAcceptSuggestion = useCallback(async () => {
    setIsAccepting(true);
    try {
      await acceptSuggestion(video.id, ["thumbnail_prompt"]);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      alert(`Failed to accept suggestion: ${(err as Error).message}`);
    } finally {
      setIsAccepting(false);
    }
  }, [video.id, queryClient]);

  const handleRejectSuggestion = useCallback(async () => {
    setIsRejecting(true);
    try {
      await rejectSuggestion(video.id);
      setSuggestionDismissed(true);
    } catch (err) {
      alert(`Failed to reject suggestion: ${(err as Error).message}`);
    } finally {
      setIsRejecting(false);
    }
  }, [video.id]);

  const [advancing, setAdvancing] = useState(false);
  const handleAdvanceStage = useCallback(async () => {
    setAdvancing(true);
    try {
      await advanceVideo(video.id);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      onAdvanced?.();
    } catch (err) {
      alert(`Failed to advance: ${(err as Error).message}`);
    } finally {
      setAdvancing(false);
    }
  }, [video.id, queryClient, onAdvanced]);

  const handleRegenerate = useCallback(async () => {
    if (!isReadyForThumbnail) return;
    setIsRegenerating(true);
    setIsApproved(false);
    try {
      await runPipelineStage(video.id, "thumbnail");
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "thumbnail");
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          alert(`Thumbnail generation failed: ${(retryErr as Error).message}`);
        }
      } else if (message.includes("400") && message.includes("not ready")) {
        // Video stage changed since page loaded — refetch to show correct state
        queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      } else {
        alert(`Thumbnail generation failed: ${message}`);
      }
      setIsRegenerating(false);
    }
  }, [video.id, queryClient]);

  const handleApprove = useCallback(async () => {
    setIsApproving(true);
    try {
      await advanceVideo(video.id);
      setIsApproved(true);
      onAdvanced?.();
    } catch {
      // silent
    } finally {
      setIsApproving(false);
    }
  }, [video.id, onAdvanced]);

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

  const promptDirty = prompt !== savedPromptRef.current;

  const handleSavePrompt = useCallback(async () => {
    setIsSavingPrompt(true);
    try {
      await updateVideo(video.id, { thumbnail_prompt: prompt });
      savedPromptRef.current = prompt;
      setPromptSaved(true);
      setTimeout(() => setPromptSaved(false), 2000);
    } catch (err) {
      alert(`Failed to save prompt: ${(err as Error).message}`);
    } finally {
      setIsSavingPrompt(false);
    }
  }, [video.id, prompt]);

  const thumbnailUrl = video.thumbnail_url || vid.thumbnailUrl;

  return (
    <>
    <div className="rounded-xl px-4 py-3 mb-4" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-4 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
          <span>{thumbnailUrl ? "Thumbnail generated" : "No thumbnail yet"}</span>
        </div>
        <button onClick={handleAdvanceStage} disabled={advancing}
          className="px-3 py-1.5 rounded-lg text-[10px] font-semibold inline-flex items-center gap-1 disabled:opacity-50 transition-all hover:brightness-110"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
          {advancing ? <Loader2 size={12} className="animate-spin" /> : null}
          Advance Stage <ChevronRight size={12} />
        </button>
      </div>
    </div>
    {/* Thumbnail System Prompt */}
    <SystemPromptEditor
      label="Thumbnail System Prompt"
      currentValue={video.thumbnail_system_prompt}
      onSave={async (text) => {
        await updateVideo(video.id, { thumbnail_system_prompt: text || null });
        queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      }}
      onReset={async () => {
        const res = await getDefaultThumbnailPrompt();
        await updateVideo(video.id, { thumbnail_system_prompt: null });
        queryClient.invalidateQueries({ queryKey: ["video", video.id] });
        return res.prompt;
      }}
    />

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
              {prompt && promptDirty && (
                <button
                  onClick={handleSavePrompt}
                  disabled={isSavingPrompt}
                  className="mt-2 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                  style={{
                    background: "var(--gold-dim)",
                    color: "var(--gold)",
                    border: "1px solid var(--gold)",
                  }}
                >
                  {isSavingPrompt ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                  {isSavingPrompt ? "Saving..." : "Save Prompt"}
                </button>
              )}
              {promptSaved && !promptDirty && (
                <p className="mt-2 text-xs flex items-center gap-1" style={{ color: "var(--green)" }}>
                  <Check size={12} /> Prompt saved
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
            icon={(isRegenerating || taskRunning) ? Loader2 : thumbnailUrl ? RefreshCw : ImageIcon}
            className="w-full"
            onClick={handleRegenerate}
            disabled={isRegenerating || taskRunning || !isReadyForThumbnail}
          >
            {!isReadyForThumbnail
              ? "Complete earlier stages first"
              : taskRunning
                ? (taskMessage || "Generating...")
                : isRegenerating
                  ? "Starting..."
                  : thumbnailUrl
                    ? "Regenerate"
                    : "Generate Thumbnail"}
          </ActionButton>
          {thumbnailUrl && (
            <ActionButton
              variant="outline"
              icon={isApproving ? Loader2 : isApproved ? Check : undefined}
              className="w-full"
              onClick={handleApprove}
              disabled={isApproving || isApproved}
            >
              {isApproving
                ? "Approving..."
                : isApproved
                  ? "Approved"
                  : "Approve & Advance"}
            </ActionButton>
          )}
        </div>

        {/* Agent Suggestions */}
        {hasSuggestions && (
          <GlassCard className="p-4" style={{ borderLeftWidth: 3, borderLeftColor: "var(--purple)" }}>
            <div className="flex items-center gap-2 mb-3">
              <Sparkles size={14} style={{ color: "var(--purple)" }} />
              <h3
                className="text-xs font-semibold uppercase tracking-wider"
                style={{ color: "var(--purple)" }}
              >
                Agent Suggestions
              </h3>
            </div>
            {video.suggested_thumbnail_prompt && (
              <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
                {video.suggested_thumbnail_prompt}
              </p>
            )}
            <div className="space-y-2 mb-3">
              {video.suggested_thumbnail_urls!.map((thumb, i) => (
                <div key={i} className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
                  <img
                    src={thumb.url}
                    alt={`Suggestion ${i + 1}`}
                    className="w-full aspect-video object-cover"
                  />
                  {thumb.approach && (
                    <p className="px-2 py-1 text-[10px] font-mono" style={{ color: "var(--text-tertiary)", background: "var(--bg-deep)" }}>
                      {thumb.approach}
                    </p>
                  )}
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <ActionButton
                variant="filled"
                icon={isAccepting ? Loader2 : Check}
                className="flex-1"
                onClick={handleAcceptSuggestion}
                disabled={isAccepting || isRejecting}
              >
                {isAccepting ? "Accepting..." : "Accept"}
              </ActionButton>
              <ActionButton
                variant="warning"
                icon={isRejecting ? Loader2 : X}
                className="flex-1"
                onClick={handleRejectSuggestion}
                disabled={isAccepting || isRejecting}
              >
                {isRejecting ? "..." : "Reject"}
              </ActionButton>
            </div>
          </GlassCard>
        )}
      </div>
    </div>
    </>
  );
}
