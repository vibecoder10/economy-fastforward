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
 *
 * C2 (feat/per-card-parallel-clips) — per-card Run/Re-run coalescing:
 * `animateOne` no longer dials the backend directly. It drops the asset
 * into `pendingClipRef` (a plain Map, so several taps inside one render
 * tick collapse onto the same id) and arms a short debounce
 * (CLIP_BATCH_DEBOUNCE_MS). When the debounce fires, `dispatchPendingClips`
 * sends every id collected so far as ONE call — a single `asset_id=` when
 * there's exactly one (byte-identical to the pre-C2 request shape), or
 * `asset_ids=a,b,c` for two-plus, which C1's backend fans out in parallel
 * under CLIP_CONCURRENCY. `force` is a single boolean per backend call (not
 * per asset) — see routes/pipeline.py's run_clip — so a batch that mixes a
 * fresh card with a redo sends `force=true` for the whole batch; that's
 * provably harmless for the fresh card too (pipeline_executor's candidate
 * filter is `force or not video_clip_url`, force's only use in that
 * function), never a behavior change for it.
 *
 * A tap is never blocked by an in-flight run — clicking just grows the
 * pending Map and the card shows "queued" (see `queuedClipIds`). If a batch
 * is already dispatched (running=true) when the debounce fires,
 * dispatchPendingClips no-ops and leaves everything queued; the
 * running→idle effect below (which already drives "Animate the rest"'s
 * auto-resume) retries it the moment the slot frees — so several edits
 * made while a run is in flight still coalesce into ONE follow-up call
 * instead of trickling out one request per card. A max-wait
 * (CLIP_BATCH_MAX_WAIT_MS) stops a continuous stream of clicks from
 * starving the debounce forever.
 *
 * `animateScene`/`animateAll` are UNCHANGED — they still call startClipTask
 * directly and are still blocked by `running` (toast + no-op), same as
 * before C2. Only the per-card path routes through the queue.
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

// C2: coalescing window for per-card clicks — several taps inside this
// many ms collapse onto one asset_ids=a,b,c backend call.
const CLIP_BATCH_DEBOUNCE_MS = 500;
// C2: even under a continuous stream of clicks (each one resetting the
// debounce), never let the first-queued card wait longer than this before
// a batch goes out.
const CLIP_BATCH_MAX_WAIT_MS = 2000;

export function useClipTrustLadder({
  videoId, running, taskMessage, markStarted, toast, refreshAll,
}: UseClipTrustLadderOptions) {
  const [generatingClipIds, setGeneratingClipIds] = useState<Set<string>>(new Set());
  const [failedClipIds, setFailedClipIds] = useState<Set<string>>(new Set());
  // C2: cards clicked but not yet dispatched to the backend — either still
  // inside the debounce window, or waiting for an in-flight batch to free
  // up. Mirrors generatingClipIds/failedClipIds as a third per-card state.
  const [queuedClipIds, setQueuedClipIds] = useState<Set<string>>(new Set());
  const [confirmKey, setConfirmKey] = useState<string | null>(null); // "scene-3" | "all"

  // Clip auto-resume: "Animate the rest" keeps re-triggering the additive backend
  // (each round only animates clips still missing a video_clip_url) until every clip
  // is done — surviving server restarts and transient failures with no manual
  // re-click and no double-charge. Guards below stop any runaway loop.
  const clipResumeRef = useRef<{ active: boolean; rounds: number; lastPending: number; stale: number }>(
    { active: false, rounds: 0, lastPending: Infinity, stale: 0 });
  const prevRunningRef = useRef(false);

  // C2: id -> force, for cards clicked but not yet sent. A plain Map (not
  // state) so rapid clicks never fight React's batching — state
  // (queuedClipIds) is derived from it after every mutation, for rendering.
  const pendingClipRef = useRef<Map<string, boolean>>(new Map());
  const clipFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSinceRef = useRef<number | null>(null);
  // Mirrors `running` synchronously for the debounce timer's callback, which
  // fires outside React's render cycle and would otherwise close over
  // whatever `running` was at the moment the timer was armed, not "now".
  const runningRef = useRef(running);
  runningRef.current = running;

  const startClipTask = useCallback(async (params: Record<string, string | number>, ids: string[]) => {
    // C2: reads runningRef (not the closed-over `running` state) — this can
    // now be invoked from a debounce timer firing well after the render
    // that created this closure, where a stale `running` would be wrong.
    // dispatchPendingClips already checked the same ref synchronously right
    // before calling this, so the two checks can never disagree.
    if (runningRef.current) {
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
  }, [taskMessage, videoId, toast, markStarted]);

  // C2: fires whatever's in pendingClipRef as ONE call. No-ops (leaving the
  // queue intact) while a run is already in flight — the running→idle
  // effect below is what retries this once the slot frees, so a batch that
  // arrives mid-run still coalesces instead of firing early.
  const dispatchPendingClips = useCallback(() => {
    if (runningRef.current) return;
    if (pendingClipRef.current.size === 0) return;
    const entries = Array.from(pendingClipRef.current.entries());
    pendingClipRef.current = new Map();
    pendingSinceRef.current = null;
    setQueuedClipIds(new Set());
    clipResumeRef.current.active = false;  // a per-card batch isn't the auto-resume loop
    const ids = entries.map(([id]) => id);
    // Single id keeps the ORIGINAL asset_id= shape (byte-identical to pre-C2
    // requests); 2+ uses C1's asset_ids=a,b,c. force is one bool per call —
    // true if ANY queued card needs it (safe for the rest, see file header).
    const force = entries.some(([, f]) => f);
    const params: Record<string, string | number> = ids.length > 1
      ? { asset_ids: ids.join(","), ...(force ? { force: "true" } : {}) }
      : { asset_id: ids[0], ...(force ? { force: "true" } : {}) };
    void startClipTask(params, ids);
  }, [startClipTask]);

  // C2: per-card Run/Re-run — never blocked by an in-flight run. Adds the
  // card to the pending batch (deduped by id; a second click just upgrades
  // force to true) and (re)arms the debounce, capped by CLIP_BATCH_MAX_WAIT_MS
  // so a continuous stream of clicks can't starve the flush indefinitely.
  const animateOne = useCallback((asset: Asset, force = false) => {
    if (generatingClipIds.has(asset.id)) return;  // already mid-flight — ignore the dup tap
    if (pendingClipRef.current.size === 0) pendingSinceRef.current = Date.now();
    pendingClipRef.current.set(asset.id, force || (pendingClipRef.current.get(asset.id) ?? false));
    setQueuedClipIds(new Set(pendingClipRef.current.keys()));
    setFailedClipIds((prev) => {
      if (!prev.has(asset.id)) return prev;
      const next = new Set(prev);
      next.delete(asset.id);
      return next;
    });

    if (clipFlushTimerRef.current) clearTimeout(clipFlushTimerRef.current);
    const waitedAlready = Date.now() - (pendingSinceRef.current ?? Date.now());
    const wait = waitedAlready >= CLIP_BATCH_MAX_WAIT_MS ? 0 : CLIP_BATCH_DEBOUNCE_MS;
    clipFlushTimerRef.current = setTimeout(() => {
      clipFlushTimerRef.current = null;
      dispatchPendingClips();
    }, wait);
  }, [generatingClipIds, dispatchPendingClips]);

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

  // Fire the resumer on each running → idle transition. C2: also the retry
  // point for a per-card batch that arrived while the slot was busy — a
  // manual click already stood clipResumeRef.current.active down (see
  // animateOne/dispatchPendingClips), so these two branches never both fire
  // for the same transition.
  useEffect(() => {
    const wasRunning = prevRunningRef.current;
    prevRunningRef.current = running;
    if (wasRunning && !running) {
      if (clipResumeRef.current.active) {
        void maybeResumeClips();
      } else if (pendingClipRef.current.size > 0) {
        dispatchPendingClips();
      }
    }
  }, [running, maybeResumeClips, dispatchPendingClips]);

  // Debounce timer must not fire (and touch state) after unmount.
  useEffect(() => {
    return () => {
      if (clipFlushTimerRef.current) clearTimeout(clipFlushTimerRef.current);
    };
  }, []);

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
   * "completed" to pollers, which would otherwise fire the next paid round).
   * C2: also drops any cards still queued from per-card clicks — Stop means
   * stop, not "run what's left the instant the slot frees". */
  const cancelResume = useCallback(() => {
    clipResumeRef.current.active = false;
    if (clipFlushTimerRef.current) {
      clearTimeout(clipFlushTimerRef.current);
      clipFlushTimerRef.current = null;
    }
    pendingClipRef.current = new Map();
    pendingSinceRef.current = null;
    setQueuedClipIds(new Set());
  }, []);

  return {
    generatingClipIds, setGeneratingClipIds,
    failedClipIds, setFailedClipIds,
    queuedClipIds,
    confirmKey, setConfirmKey,
    animateOne, animateScene, animateAll,
    confirmable, cancelResume,
  };
}
