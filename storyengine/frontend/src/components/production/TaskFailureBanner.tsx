"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, X } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { useSharedTaskWatcher, type TaskWatcherBridge } from "@/hooks/use-task-poller";
import { humanizeError } from "@/lib/errors";

interface TaskFailureBannerProps {
  videoId: string;
  taskWatcher: TaskWatcherBridge;
}

/**
 * U5: the "NEXT UP" guided card (GuidedNextStep) was removed wholesale from
 * the regular pipeline page — Ryan's call, it duplicated the now-clickable
 * StageRail bubbles and he didn't find it useful. But that component was
 * also the ONE always-mounted subscriber to the page's shared task watcher
 * (no `enabled` gate — see use-task-poller.ts), so it was the only surface
 * that still caught a task failure after you'd navigated away from the tab
 * that started it (every tab unmounts on switch, taking its own onFailed
 * toast with it). This component keeps exactly that: a persistent
 * "That step didn't finish" card, until dismissed, with no retry button —
 * retry lives on each tab's own action button, the one reliable path.
 * Everything else GuidedNextStep did (the idle next-step CTA, the
 * draft/finalize offer, the skip-voice action, the research nudge chip, the
 * running/progress card) is gone, per Ryan's ask.
 */
export function TaskFailureBanner({ videoId, taskWatcher }: TaskFailureBannerProps) {
  const queryClient = useQueryClient();
  const [failure, setFailure] = useState<string | null>(null);

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ["video", videoId] });
    queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
    queryClient.invalidateQueries({ queryKey: ["video-characters", videoId] });
    queryClient.invalidateQueries({ queryKey: ["video-actions", videoId] });
  };

  useSharedTaskWatcher({
    bridge: taskWatcher,
    onComplete: () => {
      setFailure(null); // a finished run supersedes any earlier failure card
      refreshAll();
    },
    onFailed: (error) => {
      refreshAll();
      setFailure(humanizeError(error, "That step didn't finish."));
    },
  });
  const { running } = taskWatcher;

  if (!failure || running) return null;

  return (
    <GlassCard className="!p-4 mb-4" style={{ border: "1px solid var(--red)" }}>
      <div className="flex items-start gap-3">
        <AlertTriangle size={20} className="shrink-0 mt-0.5" style={{ color: "var(--red)" }} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold" style={{ color: "var(--red)" }}>
            That step didn&apos;t finish
          </p>
          <p className="text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>{failure}</p>
          <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
            Anything already created was kept — use the button below to pick up where it left off.
          </p>
        </div>
        <button onClick={() => setFailure(null)} title="Dismiss" className="shrink-0 p-1" style={{ color: "var(--text-tertiary)" }}>
          <X size={16} />
        </button>
      </div>
    </GlassCard>
  );
}
