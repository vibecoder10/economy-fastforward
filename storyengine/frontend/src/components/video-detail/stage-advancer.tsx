"use client";

import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, CheckCircle, AlertCircle, ChevronRight, RefreshCw } from "lucide-react";
import { runPipelineStage, advanceVideo, clearStaleTask } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import { GlassCard } from "@/components/ui/GlassCard";

/** Parse backend 400 errors into user-friendly messages with guidance */
function friendlyError(raw: string): string {
  // Extract JSON detail from "API error 400: {"detail":"..."}"
  const detailMatch = raw.match(/"detail"\s*:\s*"([^"]+)"/);
  const detail = detailMatch ? detailMatch[1] : raw;

  // New format — "Video not ready for X — needs at least Y (status: Z)"
  const needsMatch = detail.match(/not ready for (\w+)\s*—\s*needs (.+?)\s*\(status:/i);
  if (needsMatch) {
    const target = needsMatch[1].trim();
    return `Can't run ${target} yet — needs ${needsMatch[2].trim()}.`;
  }

  // Legacy format — "Video not ready for X (status: Y)"
  const statusMatch = detail.match(/not ready for (\w[\w\s]*)\(status:\s*(\w+)/i);
  if (statusMatch) {
    const target = statusMatch[1].trim();
    const current = statusMatch[2].replace(/_/g, " ");
    return `Complete the "${current}" stage first before running ${target}.`;
  }

  // API key not configured or invalid
  if (/api.key|not configured|missing.*key|invalid.*key|authentication|unauthorized/i.test(detail)) {
    return "An API key is not configured or invalid. Check Settings → API Keys.";
  }

  // Rate limit
  if (/rate.limit|Rate.limit|too many requests|429/i.test(detail)) {
    return "Rate limit hit — wait a minute and try again.";
  }

  // Timeout
  if (/timeout|Timeout|timed out|ETIMEDOUT/i.test(detail)) {
    return "Request timed out — the service may be slow. Try again.";
  }

  // Task already running
  if (/already running|task.*running/i.test(detail)) {
    return "A task is already running for this video. Wait for it to finish or clear it.";
  }

  // Missing prerequisites
  if (/no script|no voice|no images|no assets/i.test(detail)) {
    return `Missing prerequisites — ${detail.replace(/^Video\s*/i, "This video ")}`;
  }

  // 409 conflict
  if (/409/.test(raw)) {
    return "Another task is running. It will be cleared automatically — try again in a moment.";
  }

  // Plan limit
  if (/plan.limit|402/i.test(raw)) {
    return "You've reached your plan's limit. Upgrade for more capacity.";
  }

  // Fallback: clean up raw message
  return detail.replace(/^Video\s*/i, "This video ");
}

interface StageAdvancerProps {
  videoId: string;
  stage: string;
  label: string;
  nextLabel?: string;
  disabled?: boolean;
  disabledReason?: string;
  cost?: string;
  showAdvance?: boolean;
}

export function StageAdvancer({
  videoId, stage, label, nextLabel, disabled, disabledReason, cost, showAdvance,
}: StageAdvancerProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [taskRunning, setTaskRunning] = useState(false);
  const [result, setResult] = useState<"success" | "error" | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { message } = useTaskPoller({
    videoId,
    enabled: taskRunning,
    onComplete: () => {
      setTaskRunning(false);
      setResult("success");
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
      setTimeout(() => setResult(null), 3000);
    },
    onFailed: (err) => {
      setTaskRunning(false);
      const friendly = err ? friendlyError(err) : "Task failed";
      setResult("error");
      setErrorMsg(friendly);
      toast.error(friendly);
    },
  });

  const handleClick = useCallback(async () => {
    setResult(null);
    setErrorMsg(null);
    try {
      await runPipelineStage(videoId, stage);
      setTaskRunning(true);
    } catch (err: any) {
      const msg = err.message || "Failed to start";
      // Auto-retry on 409 (stale task) — clear and retry once
      if (msg.includes("409")) {
        try {
          await clearStaleTask(videoId);
          await runPipelineStage(videoId, stage);
          setTaskRunning(true);
          return;
        } catch { /* fall through to error display */ }
      }
      const friendly = friendlyError(msg);
      setResult("error");
      setErrorMsg(friendly);
      toast.error(friendly);
    }
  }, [videoId, stage, toast]);

  const handleRetry = () => {
    setResult(null);
    setErrorMsg(null);
    handleClick();
  };

  if (result === "success") {
    return (
      <div className="flex items-center gap-2 text-sm" style={{ color: "#1A8A7A" }}>
        <CheckCircle size={16} /> Done {nextLabel}
      </div>
    );
  }

  if (result === "error") {
    return (
      <GlassCard
        className="!p-3"
        style={{
          background: "rgba(255,77,106,0.08)",
          borderColor: "rgba(255,77,106,0.25)",
        }}
      >
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs" style={{ color: "var(--red)" }}>
            <AlertCircle size={14} className="inline mr-1" />
            {errorMsg || "Failed"}
          </span>
          <button
            onClick={handleRetry}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg font-medium shrink-0"
            style={{ background: "var(--red)", color: "white" }}
          >
            <RefreshCw size={12} />
            Retry
          </button>
        </div>
      </GlassCard>
    );
  }

  if (taskRunning) {
    return (
      <div className="flex items-center gap-2">
        <Loader2 size={14} className="animate-spin" style={{ color: "var(--amber)" }} />
        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
          {message || "Processing..."}
        </span>
      </div>
    );
  }

  const handleAdvance = useCallback(async () => {
    setResult(null);
    setErrorMsg(null);
    try {
      await advanceVideo(videoId);
      setResult("success");
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      setTimeout(() => setResult(null), 3000);
    } catch (err: any) {
      setResult("error");
      setErrorMsg(err.message || "Failed to advance");
    }
  }, [videoId, queryClient]);

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={handleClick}
        disabled={disabled}
        className="flex items-center gap-2 text-sm px-4 py-2 rounded-lg font-medium transition-opacity disabled:opacity-40"
        style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
        title={disabled ? disabledReason : undefined}
      >
        {label}
        {cost && <span className="opacity-60">· {cost}</span>}
      </button>
      {showAdvance && (
        <button
          onClick={handleAdvance}
          disabled={disabled}
          className="flex items-center gap-1 text-xs px-3 py-2 rounded-lg font-medium transition-opacity disabled:opacity-40"
          style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
          title="Skip to next stage"
        >
          Advance <ChevronRight size={12} />
        </button>
      )}
    </div>
  );
}
