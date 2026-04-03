"use client";

import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, CheckCircle, AlertCircle, ChevronRight } from "lucide-react";
import { runPipelineStage, advanceVideo } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";

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
      setResult("error");
      setErrorMsg(err);
    },
  });

  const handleClick = useCallback(async () => {
    setResult(null);
    setErrorMsg(null);
    try {
      await runPipelineStage(videoId, stage);
      setTaskRunning(true);
    } catch (err: any) {
      setResult("error");
      setErrorMsg(err.message || "Failed to start");
    }
  }, [videoId, stage]);

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
      <div className="flex items-center gap-2">
        <span className="text-xs" style={{ color: "#C44545" }}>
          <AlertCircle size={14} className="inline mr-1" />
          {errorMsg || "Failed"}
        </span>
        <button
          onClick={handleRetry}
          className="text-xs px-3 py-1.5 rounded-lg font-medium"
          style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
        >
          Retry
        </button>
      </div>
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
