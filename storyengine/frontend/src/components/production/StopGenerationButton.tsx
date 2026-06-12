"use client";

import { useEffect, useState } from "react";
import { Loader2, Square } from "lucide-react";
import { cancelPipelineTask } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

interface StopGenerationButtonProps {
  videoId: string;
  /** Render only while the tab's task is running. */
  running: boolean;
}

/**
 * Red Stop button shown beside any running paid generation (images, clips,
 * storyboard grids, voice). Cancellation is cooperative: the in-flight item
 * finishes, queued items are skipped, completed work is kept. The tab's
 * existing task poller sees the task complete and resets its own state.
 */
export function StopGenerationButton({ videoId, running }: StopGenerationButtonProps) {
  const toast = useToast();
  const [stopping, setStopping] = useState(false);

  // New run started (or finished) — reset the stopping state
  useEffect(() => {
    if (!running) setStopping(false);
  }, [running]);

  if (!running) return null;

  const handleStop = async () => {
    if (stopping) return;
    if (!window.confirm("Stop generation? The current item will finish, everything already generated is kept, and you can resume later.")) {
      return;
    }
    setStopping(true);
    try {
      await cancelPipelineTask(videoId);
      // A cancelled task reads as "completed" to pollers — anything queued to
      // auto-run after it (per-scene chains) must be told to stand down too.
      window.dispatchEvent(new CustomEvent("se:stop-requested", { detail: { videoId } }));
      toast.info("Stopping — the current item will finish, then generation halts.");
    } catch {
      setStopping(false);
      toast.error("Couldn't send the stop request. Try again.");
    }
  };

  return (
    <button
      onClick={handleStop}
      disabled={stopping}
      title="Stop generation — completed work is kept"
      className="px-4 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-60 flex items-center gap-2 shrink-0"
      style={{
        background: "transparent",
        color: "var(--red)",
        border: "1px solid var(--red)",
      }}
    >
      {stopping ? <Loader2 size={15} className="animate-spin" /> : <Square size={15} fill="currentColor" />}
      {stopping ? "Stopping…" : "Stop"}
    </button>
  );
}
