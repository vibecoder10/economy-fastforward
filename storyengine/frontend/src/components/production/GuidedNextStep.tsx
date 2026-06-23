"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, Loader2, Lock, RefreshCw, X } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StopGenerationButton } from "@/components/production/StopGenerationButton";
import { useToast } from "@/components/ui/toast";
import { useTaskWatcher } from "@/hooks/use-task-poller";
import {
  advanceVideo,
  designCharacters,
  getVideoAssets,
  getVideoCharacters,
  getVideoScript,
  lockStory,
  runPipelineStage,
  clearStaleTask,
  type VideoDetail,
} from "@/lib/api";
import { humanizeError } from "@/lib/errors";
import { getNextAction, NEXT_ACTION_TOTAL_STEPS } from "@/lib/next-action";

interface GuidedNextStepProps {
  video: VideoDetail & { id: string };
  onNavigate: (tab: string) => void;
  /** The video's stage plan. When it's a reduced plan, the "Step X of 10"
   * counter (which counts the full pipeline) is dropped — it would be wrong. */
  planStages?: string[] | null;
}

/**
 * THE one next-step surface for the whole page. One big button that always
 * knows what's next; a live progress line with Stop whenever ANYTHING is
 * running (no matter which control started it — it watches the video's task
 * slot continuously); a PERSISTENT error card when something fails.
 * Grandma flow: click the big button → wait → click the next big button.
 */
export function GuidedNextStep({ video, onNavigate, planStages }: GuidedNextStepProps) {
  const reducedPlan = !!planStages && planStages.length > 0;
  const queryClient = useQueryClient();
  const toast = useToast();
  const [starting, setStarting] = useState(false);
  const [locking, setLocking] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [skipConfirm, setSkipConfirm] = useState(false);
  const [skipping, setSkipping] = useState(false);

  const doSkip = async () => {
    if (!action.skip) return;
    setSkipping(true);
    try {
      await advanceVideo(video.id, action.skip.to);
      setSkipConfirm(false);
      refreshAll();
      toast.success("Skipped — on to the next step.");
    } catch (err) {
      toast.error(humanizeError(err, "We couldn't skip that step."));
    } finally {
      setSkipping(false);
    }
  };

  const { data: charData } = useQuery({
    queryKey: ["video-characters", video.id],
    queryFn: () => getVideoCharacters(video.id),
  });
  const { data: scriptData } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });
  const { data: assetData } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });

  const scenes = scriptData ?? [];
  const assets = assetData ?? [];
  const action = getNextAction({
    video,
    characters: charData?.characters ?? [],
    charactersApprovedAt: charData?.approved_at ?? null,
    scenesWithGrids: scenes.filter(
      (s) => s.storyboard_1_url || s.storyboard_2_url || s.storyboard_3_url
    ).length,
    totalScenes: scenes.length,
    extractedCount: assets.filter((a) => a.image_url).length,
    totalSegments: assets.length,
    clipsDone: assets.filter((a) => a.video_clip_url).length,
    clipsTotal: assets.filter((a) => a.image_url).length,
    // Distinct scenes that actually have pictures. In the coverage flow a scene
    // with no pictures has NO asset rows, so asset counts alone can't tell it's
    // missing — compare this against totalScenes to avoid a premature "Animate".
    scenesWithPictures: new Set(assets.filter((a) => a.image_url).map((a) => a.scene)).size,
  });

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-characters", video.id] });
  };

  const { running, message: taskMessage, markStarted } = useTaskWatcher({
    videoId: video.id,
    onComplete: (msg) => {
      setFailure(null); // a finished run supersedes any earlier failure card
      refreshAll();
      if (msg && /needs approval|approve/i.test(msg)) toast.info(msg);
      else if (msg) toast.success(msg);
    },
    onFailed: (error) => {
      refreshAll();
      setFailure(humanizeError(error, "That step didn't finish."));
    },
  });

  const handleLock = async () => {
    if (!window.confirm(
      "Lock the story? This says: I've looked at every board and I'm happy.\n\nThe final pictures are created from these boards. You can unlock later if you change your mind."
    )) return;
    setLocking(true);
    try {
      await lockStory(video.id);
      refreshAll();
      // The final pictures start AUTOMATICALLY — extraction is plumbing, not
      // a decision, so the user never sees it as a step. Progress shows in
      // this banner; if it fails, the banner's recovery action picks it up.
      try {
        try { await clearStaleTask(video.id); } catch { /* fine */ }
        await runPipelineStage(video.id, "storyboard-extract");
        markStarted();
        toast.success("Story locked — making your final pictures now.");
      } catch {
        toast.success("Story locked.");
      }
    } catch (err) {
      setFailure(humanizeError(err, "We couldn't lock the story."));
    } finally {
      setLocking(false);
    }
  };

  const start = async () => {
    setFailure(null);
    onNavigate(action.tab);
    if (action.kind === "lock") {
      await handleLock();
      return;
    }
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
      markStarted();
    } catch (err) {
      const msg = (err as Error).message || "";
      if (msg.includes("409")) {
        // Something is already running — just watch it.
        toast.info("Already working on something — watching it.");
        markStarted();
      } else {
        setFailure(humanizeError(err, "We couldn't start that step."));
      }
    } finally {
      setStarting(false);
    }
  };

  // ---------- FAILED: persistent until retried or dismissed ----------
  if (failure && !running) {
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

  // ---------- RUNNING: live progress + Stop (any task, any starter) ----------
  if (running || starting || locking) {
    return (
      <GlassCard className="!p-4 mb-4" style={{ border: "1px solid var(--turquoise)" }}>
        <div className="flex items-center gap-3">
          <Loader2 size={20} className="animate-spin shrink-0" style={{ color: "var(--turquoise)" }} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }}>
              {locking
                ? "Locking the story…"
                : (taskMessage || `Working on it — ${action.label.toLowerCase()}…`)}
            </p>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>
              You can leave this page — your video keeps working in the background.
            </p>
          </div>
          {!locking && <StopGenerationButton videoId={video.id} running={running} />}
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

  // ---------- IDLE: the one big next button (+ a clear Skip for optional steps) ----------
  return (
    <GlassCard className="!p-5 mb-4" style={{ border: "1px solid var(--turquoise)" }}>
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex-1 min-w-[220px]">
          <p className="text-[11px] font-mono uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
            {reducedPlan ? "Next up" : `Step ${action.step} of ${NEXT_ACTION_TOTAL_STEPS} · Next up`}
          </p>
          <p className="text-base font-semibold mt-0.5" style={{ color: "var(--text-primary)" }}>
            {action.description}
          </p>
        </div>
        <button
          onClick={start}
          className="px-7 py-4 rounded-2xl text-base font-bold flex items-center gap-2.5 shrink-0 transition-all hover:brightness-110 active:scale-[0.98]"
          style={{
            background: action.kind === "lock" ? "var(--gold)" : "var(--turquoise)",
            color: "var(--bg-void)",
            boxShadow: action.kind === "lock"
              ? "0 4px 24px rgba(255, 186, 8, 0.18)"
              : "0 4px 24px rgba(0, 245, 212, 0.15)",
          }}
        >
          {action.kind === "lock" && <Lock size={18} />}
          {action.label}
          {action.cost && (
            <span className="text-xs font-mono font-normal opacity-80">{action.cost}</span>
          )}
          {action.kind !== "lock" && <ArrowRight size={18} />}
        </button>
      </div>
      {action.skip && !skipConfirm && (
        <div className="flex justify-end mt-2.5">
          <button
            onClick={() => setSkipConfirm(true)}
            className="text-sm font-medium px-3 py-1.5 rounded-xl transition-all hover:brightness-110 hover:bg-white/10"
            style={{ color: "var(--text-primary)", border: "1px solid rgba(255,255,255,0.25)" }}
          >
            I don&apos;t need this — skip it →
          </button>
        </div>
      )}
      {action.skip && skipConfirm && (
        <div className="flex items-center gap-3 mt-3 pt-3 flex-wrap" style={{ borderTop: "1px solid rgba(255,255,255,0.08)" }}>
          <p className="text-xs flex-1 min-w-[200px]" style={{ color: "var(--text-secondary)" }}>
            {action.skip.note} You can come back to it any time.
          </p>
          <button
            onClick={doSkip}
            disabled={skipping}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-40 transition-all hover:brightness-110"
            style={{ background: "rgba(255,255,255,0.12)", color: "var(--text-primary)" }}
          >
            {skipping ? "Skipping…" : "Yes, skip this step"}
          </button>
          <button onClick={() => setSkipConfirm(false)} className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            Keep it
          </button>
        </div>
      )}
    </GlassCard>
  );
}
