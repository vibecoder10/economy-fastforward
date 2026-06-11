"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, Loader2, RefreshCw, X } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StopGenerationButton } from "@/components/production/StopGenerationButton";
import { useToast } from "@/components/ui/toast";
import { useTaskPoller } from "@/hooks/use-task-poller";
import {
  designCharacters,
  getVideoCharacters,
  getVideoScript,
  runPipelineStage,
  clearStaleTask,
  type VideoDetail,
} from "@/lib/api";
import { humanizeError } from "@/lib/errors";
import { getNextAction, NEXT_ACTION_TOTAL_STEPS } from "@/lib/next-action";

interface GuidedNextStepProps {
  video: VideoDetail & { id: string };
  onNavigate: (tab: string) => void;
}

/**
 * THE guided banner. One big button that always knows what's next, a live
 * progress line while work runs (with Stop), and a PERSISTENT error card when
 * something fails (no more 6-second toasts hiding a dead pipeline).
 * Grandma flow: click the big button → wait → click the next big button.
 */
export function GuidedNextStep({ video, onNavigate }: GuidedNextStepProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [running, setRunning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const { data: charData } = useQuery({
    queryKey: ["video-characters", video.id],
    queryFn: () => getVideoCharacters(video.id),
  });
  const { data: scriptData } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });

  const scenes = scriptData ?? [];
  const action = getNextAction({
    video,
    characters: charData?.characters ?? [],
    charactersApprovedAt: charData?.approved_at ?? null,
    scenesWithGrids: scenes.filter(
      (s) => s.storyboard_1_url || s.storyboard_2_url || s.storyboard_3_url
    ).length,
    totalScenes: scenes.length,
  });

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-characters", video.id] });
  };

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: running,
    interval: 3000,
    onComplete: (msg) => {
      setRunning(false);
      refreshAll();
      if (msg) toast.success(msg);
    },
    onFailed: (error) => {
      setRunning(false);
      refreshAll();
      setFailure(humanizeError(error, "That step didn't finish."));
    },
  });

  const start = async () => {
    setFailure(null);
    onNavigate(action.tab);
    if (action.kind === "review" || action.kind === "celebrate") {
      return; // the decision lives in the tab we just opened
    }
    setStarting(true);
    try {
      try { await clearStaleTask(video.id); } catch { /* fine */ }
      if (action.kind === "design") {
        await designCharacters(video.id);
      } else if (action.stage) {
        await runPipelineStage(video.id, action.stage);
      }
      setRunning(true);
    } catch (err) {
      const msg = (err as Error).message || "";
      if (msg.includes("409")) {
        // Something is already running — just watch it.
        setRunning(true);
      } else {
        setFailure(humanizeError(err, "We couldn't start that step."));
      }
    } finally {
      setStarting(false);
    }
  };

  // ---------- FAILED: persistent until retried or dismissed ----------
  if (failure) {
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
              Anything already created was kept — trying again only does the missing part.
            </p>
          </div>
          <button
            onClick={start}
            className="px-4 py-2 rounded-xl text-sm font-bold shrink-0 flex items-center gap-2 transition-all hover:brightness-110"
            style={{ background: "var(--red)", color: "var(--bg-void)" }}
          >
            <RefreshCw size={14} /> Try again
          </button>
          <button onClick={() => setFailure(null)} title="Dismiss" className="shrink-0 p-1" style={{ color: "var(--text-tertiary)" }}>
            <X size={16} />
          </button>
        </div>
      </GlassCard>
    );
  }

  // ---------- RUNNING: live progress + Stop ----------
  if (running || starting) {
    return (
      <GlassCard className="!p-4 mb-4" style={{ border: "1px solid var(--turquoise)" }}>
        <div className="flex items-center gap-3">
          <Loader2 size={20} className="animate-spin shrink-0" style={{ color: "var(--turquoise)" }} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }}>
              {taskMessage || `Working on it — ${action.label.toLowerCase()}…`}
            </p>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>
              You can leave this page — your video keeps working in the background.
            </p>
          </div>
          <StopGenerationButton videoId={video.id} running={running} />
        </div>
      </GlassCard>
    );
  }

  // ---------- DONE ----------
  if (action.kind === "celebrate") {
    return (
      <GlassCard className="!p-4 mb-4" style={{ border: "1px solid var(--green)" }}>
        <div className="flex items-center gap-3">
          <CheckCircle2 size={20} className="shrink-0" style={{ color: "var(--green)" }} />
          <div className="flex-1">
            <p className="text-sm font-semibold" style={{ color: "var(--green)" }}>Your video is made 🎉</p>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>{action.description}</p>
          </div>
          <button
            onClick={() => onNavigate(action.tab)}
            className="px-4 py-2 rounded-xl text-sm font-semibold shrink-0"
            style={{ color: "var(--green)", border: "1px solid var(--green)" }}
          >
            {action.label}
          </button>
        </div>
      </GlassCard>
    );
  }

  // ---------- IDLE: the one big next button ----------
  return (
    <GlassCard className="!p-4 mb-4" style={{ border: "1px solid var(--turquoise)" }}>
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex-1 min-w-[220px]">
          <p className="text-[11px] font-mono uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
            Step {action.step} of {NEXT_ACTION_TOTAL_STEPS} · Next up
          </p>
          <p className="text-base font-semibold mt-0.5" style={{ color: "var(--text-primary)" }}>
            {action.description}
          </p>
        </div>
        <button
          onClick={start}
          className="px-6 py-3.5 rounded-xl text-base font-bold flex items-center gap-2 shrink-0 transition-all hover:brightness-110 active:scale-[0.98]"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        >
          {action.label}
          {action.cost && (
            <span className="text-xs font-mono font-normal opacity-80">{action.cost}</span>
          )}
          <ArrowRight size={18} />
        </button>
      </div>
    </GlassCard>
  );
}
