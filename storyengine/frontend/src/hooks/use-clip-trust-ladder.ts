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
 *
 * C3 (feat/per-card-parallel-clips) — per-card picture Redraw gets the exact
 * same coalescing treatment, as a second, parallel track living in this same
 * hook rather than a sibling hook: `redrawOne`/`dispatchPendingRedraws`/
 * `pendingRedrawRef` mirror `animateOne`/`dispatchPendingClips`/
 * `pendingClipRef` line for line (no `force` concept — every redraw call is
 * inherently a redo, unlike clip's Run-vs-Redo), and it reuses the SAME
 * `running`/`runningRef`/`markStarted`/options this hook already takes, plus
 * the SAME running→idle effect (extended, not duplicated) to flush a queued
 * redraw batch the moment the video's task slot frees. Kept in this file
 * instead of a new hook because every option/ref/effect it needs already
 * exists here for clips — a sibling hook would just re-import videoId/
 * running/taskMessage/markStarted/toast/refreshAll and re-derive the same
 * running→idle wiring, for no isolation benefit (nothing else in the app
 * uses one track without the other).
 *
 * The backend (routes/pipeline.py's "redraw_manual" lane, C1b) genuinely
 * allows a redraw batch to run concurrently with a clip batch — neither
 * blocks the other, only "main" does. This hook deliberately does NOT
 * exploit that: both tracks share one `dispatchInFlightRef` gate, so at
 * most one network call (a clip batch OR a redraw batch) is ever actually
 * in flight at a time. Reason: `_running_tasks[(tenant,video_id)]` is a
 * SINGLE slot on the backend, overwritten by whichever call's progress
 * callback writes last — if both tracks dispatched at once, the shared
 * `useSharedTaskWatcher`'s running→idle transition (which this whole
 * reconcile/onComplete story depends on) could fire prematurely off the
 * FIRST one to finish while the second is still working, misfiring
 * onComplete/onFailed for work that hasn't landed yet. Serializing the two
 * tracks avoids that class of bug entirely, at the cost of not using the
 * backend's real dual-lane concurrency between clip and redraw batches —
 * WITHIN each track, multiple cards still fire as one truly parallel
 * `asset_ids=a,b,c` call, which is what this chunk asked for. See
 * `dispatchInFlightRef`'s own comment below for the mechanics.
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

  // C3: redraw's own generating/failed/queued state — same three-state shape
  // as clip's, kept as separate Sets (a card can only ever be in ONE track at
  // a time in practice, but nothing here assumes that).
  const [generatingRedrawIds, setGeneratingRedrawIds] = useState<Set<string>>(new Set());
  const [failedRedrawIds, setFailedRedrawIds] = useState<Set<string>>(new Set());
  const [queuedRedrawIds, setQueuedRedrawIds] = useState<Set<string>>(new Set());

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
  // C3: redraw's own pending set + debounce timer — no per-id "force" flag
  // needed (a redraw call is always a redo), so a plain Set is enough.
  const pendingRedrawRef = useRef<Set<string>>(new Set());
  const redrawFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const redrawSinceRef = useRef<number | null>(null);
  // Mirrors `running` synchronously for the debounce timer's callback, which
  // fires outside React's render cycle and would otherwise close over
  // whatever `running` was at the moment the timer was armed, not "now".
  const runningRef = useRef(running);
  runningRef.current = running;
  // C3: the cross-track guard clip and redraw share (see file header for the
  // full reasoning). Set true the instant EITHER track decides to actually
  // fire a network call, before the `await` inside start*Task — closing the
  // synchronous window (start*Task doesn't call markStarted(), which is what
  // flips `running`/`runningRef`, until AFTER its request resolves) where the
  // OTHER track's dispatch could otherwise slip through in the same tick and
  // send a second concurrent call. Reset to false in start*Task's `finally`,
  // once that call has fully settled one way or the other.
  const dispatchInFlightRef = useRef(false);

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
    } finally {
      // C3: release the cross-track guard now that this call has fully
      // settled (succeeded, retried, or failed) — see its declaration above.
      dispatchInFlightRef.current = false;
    }
  }, [taskMessage, videoId, toast, markStarted]);

  // C2: fires whatever's in pendingClipRef as ONE call. No-ops (leaving the
  // queue intact) while a run is already in flight — the running→idle
  // effect below is what retries this once the slot frees, so a batch that
  // arrives mid-run still coalesces instead of firing early.
  const dispatchPendingClips = useCallback(() => {
    // C3: dispatchInFlightRef also blocks this while a REDRAW batch's call
    // is mid-flight (see the shared guard's comment above).
    if (runningRef.current || dispatchInFlightRef.current) return;
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
    dispatchInFlightRef.current = true;
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

  // C3: redraw's start*Task — same 409-retry shape as startClipTask, minus
  // the `force` concept (every redraw call is inherently a redo).
  const startRedrawTask = useCallback(async (params: Record<string, string | number>, ids: string[]) => {
    if (runningRef.current) {
      toast.info(`Hang on — still working: ${taskMessage || "finishing the current step"}. This card will be tappable the moment it's done.`);
      return;
    }
    setFailedRedrawIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
    setGeneratingRedrawIds(new Set(ids));
    try {
      await runPipelineStage(videoId, "redraw-image", params);
      markStarted();
    } catch (err) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(videoId);
          await runPipelineStage(videoId, "redraw-image", params);
          markStarted();
          return;
        } catch (retryErr) {
          toast.error((retryErr as Error).message);
        }
      } else {
        toast.error(message || "Couldn't start the redraw.");
      }
      setGeneratingRedrawIds(new Set());
    } finally {
      dispatchInFlightRef.current = false;
    }
  }, [taskMessage, videoId, toast, markStarted]);

  // C3: mirrors dispatchPendingClips — fires whatever's in pendingRedrawRef
  // as ONE call (asset_ids=a,b,c for 2+, asset_id= for exactly one).
  const dispatchPendingRedraws = useCallback(() => {
    if (runningRef.current || dispatchInFlightRef.current) return;
    if (pendingRedrawRef.current.size === 0) return;
    const ids = Array.from(pendingRedrawRef.current);
    pendingRedrawRef.current = new Set();
    redrawSinceRef.current = null;
    setQueuedRedrawIds(new Set());
    const params: Record<string, string | number> = ids.length > 1
      ? { asset_ids: ids.join(",") }
      : { asset_id: ids[0] };
    dispatchInFlightRef.current = true;
    void startRedrawTask(params, ids);
  }, [startRedrawTask]);

  // C3: per-card Redraw — mirrors animateOne. Never blocked by an in-flight
  // run; adds the card to the pending redraw batch and (re)arms the same
  // debounce shape clip uses.
  const redrawOne = useCallback((asset: Asset) => {
    if (generatingRedrawIds.has(asset.id)) return;  // already mid-flight — ignore the dup tap
    if (pendingRedrawRef.current.size === 0) redrawSinceRef.current = Date.now();
    pendingRedrawRef.current.add(asset.id);
    setQueuedRedrawIds(new Set(pendingRedrawRef.current));
    setFailedRedrawIds((prev) => {
      if (!prev.has(asset.id)) return prev;
      const next = new Set(prev);
      next.delete(asset.id);
      return next;
    });

    if (redrawFlushTimerRef.current) clearTimeout(redrawFlushTimerRef.current);
    const waitedAlready = Date.now() - (redrawSinceRef.current ?? Date.now());
    const wait = waitedAlready >= CLIP_BATCH_MAX_WAIT_MS ? 0 : CLIP_BATCH_DEBOUNCE_MS;
    redrawFlushTimerRef.current = setTimeout(() => {
      redrawFlushTimerRef.current = null;
      dispatchPendingRedraws();
    }, wait);
  }, [generatingRedrawIds, dispatchPendingRedraws]);

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
  // for the same transition. C3: also the retry point for a queued redraw
  // batch — checked unconditionally (not an else-if against the clip
  // branches above) so a redraw queued while a clip batch/resume was running
  // still gets its turn the moment the slot frees. If dispatchPendingClips
  // (or maybeResumeClips) just claimed dispatchInFlightRef this same tick,
  // dispatchPendingRedraws no-ops and stays queued for the transition after.
  useEffect(() => {
    const wasRunning = prevRunningRef.current;
    prevRunningRef.current = running;
    if (wasRunning && !running) {
      if (clipResumeRef.current.active) {
        void maybeResumeClips();
      } else if (pendingClipRef.current.size > 0) {
        dispatchPendingClips();
      }
      if (pendingRedrawRef.current.size > 0) {
        dispatchPendingRedraws();
      }
    }
  }, [running, maybeResumeClips, dispatchPendingClips, dispatchPendingRedraws]);

  // Debounce timer must not fire (and touch state) after unmount.
  useEffect(() => {
    return () => {
      if (clipFlushTimerRef.current) clearTimeout(clipFlushTimerRef.current);
      if (redrawFlushTimerRef.current) clearTimeout(redrawFlushTimerRef.current);
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
   * stop, not "run what's left the instant the slot frees". C3: same for
   * any cards queued on the redraw track. */
  const cancelResume = useCallback(() => {
    clipResumeRef.current.active = false;
    if (clipFlushTimerRef.current) {
      clearTimeout(clipFlushTimerRef.current);
      clipFlushTimerRef.current = null;
    }
    pendingClipRef.current = new Map();
    pendingSinceRef.current = null;
    setQueuedClipIds(new Set());
    if (redrawFlushTimerRef.current) {
      clearTimeout(redrawFlushTimerRef.current);
      redrawFlushTimerRef.current = null;
    }
    pendingRedrawRef.current = new Set();
    redrawSinceRef.current = null;
    setQueuedRedrawIds(new Set());
  }, []);

  return {
    generatingClipIds, setGeneratingClipIds,
    failedClipIds, setFailedClipIds,
    queuedClipIds,
    generatingRedrawIds, setGeneratingRedrawIds,
    failedRedrawIds, setFailedRedrawIds,
    queuedRedrawIds,
    redrawOne,
    confirmKey, setConfirmKey,
    animateOne, animateScene, animateAll,
    confirmable, cancelResume,
  };
}
