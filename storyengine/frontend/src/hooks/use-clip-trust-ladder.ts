"use client";

/**
 * useClipTrustLadder — the clip animate/confirm/auto-resume state machine,
 * extracted from ScenesWorkspaceTab.tsx (S9-7, prep for C23's camera chips
 * so that file stops growing before the chip/sheet lands in it).
 *
 * Contract (unchanged from the inline version — this is a pure relocation):
 * - Trust ladder: tap a card = animate (~$0.09, no confirm), only actions
 *   over $0.50 (confirmable()) ask first.
 * - "Animate the rest" arms auto-resume: after each clip batch ends, if
 *   clips are still missing, re-trigger the additive backend endpoint until
 *   none remain, no progress happens twice in a row, or a safety cap (25
 *   rounds / 2 stale rounds) is hit. Never double-charges (additive).
 *
 * The caller (ScenesWorkspaceTab) still owns generatingScene/chainRef/
 * recropping and still resets this hook's generatingClipIds/failedClipIds/
 * confirmKey from its own onComplete/onFailed/Stop handlers — those handlers
 * serve storyboard-chain concerns too and were left in place, not moved
 * here, to keep this extraction behavior-preserving rather than a deeper
 * restructor.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { getVideoAssets, runPipelineStage, clearStaleTask } from "@/lib/api";
import type { Asset } from "@/lib/api";

interface ToastLike {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

interface UseClipTrustLadderOptions {
  videoId: string;
  running: boolean;
  taskMessage: string | null;
  markStarted: () => void;
  toast: ToastLike;
  refreshAll: () => void;
}

export function useClipTrustLadder({
  videoId, running, taskMessage, markStarted, toast, refreshAll,
}: UseClipTrustLadderOptions) {
  const [generatingClipIds, setGeneratingClipIds] = useState<Set<string>>(new Set());
  const [failedClipIds, setFailedClipIds] = useState<Set<string>>(new Set());
  const [confirmKey, setConfirmKey] = useState<string | null>(null); // "scene-3" | "all"

  // Clip auto-resume: "Animate the rest" keeps re-triggering the additive backend
  // (each round only animates clips still missing a video_clip_url) until every clip
  // is done — surviving server restarts and transient failures with no manual
  // re-click and no double-charge. Guards below stop any runaway loop.
  const clipResumeRef = useRef<{ active: boolean; rounds: number; lastPending: number; stale: number }>(
    { active: false, rounds: 0, lastPending: Infinity, stale: 0 });
  const prevRunningRef = useRef(false);

  const startClipTask = useCallback(async (params: Record<string, string | number>, ids: string[]) => {
    if (running) {
      toast.info(`Hang on — still working: ${taskMessage || "finishing the current step"}. This card will be tappable the moment it's done.`);
      return;
    }
    setFailedClipIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
    setGeneratingClipIds(new Set(ids));
    try {
      await runPipelineStage(videoId, "clip", params);
      markStarted();
    } catch (err) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(videoId);
          await runPipelineStage(videoId, "clip", params);
          markStarted();
          return;
        } catch (retryErr) {
          toast.error((retryErr as Error).message);
        }
      } else {
        toast.error(message || "Couldn't start the clip.");
      }
      setGeneratingClipIds(new Set());
    }
  }, [running, taskMessage, videoId, toast, markStarted]);

  const animateOne = useCallback((asset: Asset, force = false) => {
    clipResumeRef.current.active = false;  // a manual single-card tap isn't a batch
    startClipTask(force ? { asset_id: asset.id, force: "true" } : { asset_id: asset.id }, [asset.id]);
  }, [startClipTask]);

  const animateScene = useCallback((scene: number, pendingIds: string[]) => {
    clipResumeRef.current.active = false;  // a single-scene run isn't the full batch
    startClipTask({ scene }, pendingIds);
  }, [startClipTask]);

  const animateAll = useCallback((pendingIds: string[]) => {
    // Arm auto-resume: keep going until the backend says nothing's left to animate.
    clipResumeRef.current = { active: true, rounds: 0, lastPending: Infinity, stale: 0 };
    startClipTask({}, pendingIds);
  }, [startClipTask]);

  // After each clip batch ends (done, failed, or "server restarted"), if clips are
  // still missing, re-trigger — until none remain, no progress happens twice in a
  // row, or a safety cap is hit. The backend is additive, so this never double-charges.
  const maybeResumeClips = useCallback(async () => {
    const st = clipResumeRef.current;
    if (!st.active) return;
    let pending: string[] = [];
    try {
      const fresh = await getVideoAssets(videoId);
      pending = fresh.filter((a) => a.image_url && !a.video_clip_url).map((a) => a.id);
    } catch {
      st.active = false;  // can't check — stop rather than loop blind
      return;
    }
    if (pending.length === 0) {
      st.active = false;
      toast.success("All clips animated 🎬");
      refreshAll();
      return;
    }
    st.rounds += 1;
    if (pending.length < st.lastPending) st.stale = 0;
    else st.stale += 1;
    st.lastPending = pending.length;
    if (st.rounds > 25 || st.stale >= 2) {
      st.active = false;
      toast.error(`${pending.length} clip(s) still need animating — tap "Animate the rest" to keep going.`);
      refreshAll();
      return;
    }
    await new Promise((r) => setTimeout(r, 1500));
    if (clipResumeRef.current.active) startClipTask({}, pending);
  }, [videoId, toast, refreshAll, startClipTask]);

  // Fire the resumer on each running → idle transition.
  useEffect(() => {
    const wasRunning = prevRunningRef.current;
    prevRunningRef.current = running;
    if (wasRunning && !running && clipResumeRef.current.active) {
      void maybeResumeClips();
    }
  }, [running, maybeResumeClips]);

  /** Confirm-then-run for anything over $0.50; cheaper actions just go. */
  const confirmable = useCallback((key: string, dollars: number, run: () => void) => {
    if (dollars <= 0.5 || confirmKey === key) {
      setConfirmKey(null);
      run();
    } else {
      setConfirmKey(key);
    }
  }, [confirmKey]);

  /** Stop must stand down the auto-resume loop too (a cancelled task reads as
   * "completed" to pollers, which would otherwise fire the next paid round). */
  const cancelResume = useCallback(() => {
    clipResumeRef.current.active = false;
  }, []);

  return {
    generatingClipIds, setGeneratingClipIds,
    failedClipIds, setFailedClipIds,
    confirmKey, setConfirmKey,
    animateOne, animateScene, animateAll,
    confirmable, cancelResume,
  };
}
