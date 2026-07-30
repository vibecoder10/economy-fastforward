"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { getPipelineTaskStatus, TaskStatus } from "@/lib/api";

interface UseTaskPollerOptions {
  videoId: string;
  enabled: boolean;
  interval?: number;
  onComplete?: (message?: string | null) => void;
  onFailed?: (error: string) => void;
  onProgress?: (message: string | null) => void;
}

interface TaskPollerState {
  status: TaskStatus["status"] | "idle";
  message: string | null;
  error: string | null;
}

export function useTaskPoller({
  videoId,
  enabled,
  interval = 3000,
  onComplete,
  onFailed,
  onProgress,
}: UseTaskPollerOptions) {
  const [state, setState] = useState<TaskPollerState>({
    status: "idle",
    message: null,
    error: null,
  });
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onCompleteRef = useRef(onComplete);
  const onFailedRef = useRef(onFailed);
  const onProgressRef = useRef(onProgress);
  onCompleteRef.current = onComplete;
  onFailedRef.current = onFailed;
  onProgressRef.current = onProgress;

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    setState({ status: "running", message: "Starting...", error: null });

    const poll = async () => {
      try {
        const task = await getPipelineTaskStatus(videoId);
        setState({
          status: task.status,
          message: task.message,
          error: task.error || null,
        });

        if (task.status === "running") {
          onProgressRef.current?.(task.message);
        } else if (task.status === "completed") {
          stopPolling();
          onCompleteRef.current?.(task.message);
        } else if (task.status === "failed") {
          stopPolling();
          onFailedRef.current?.(task.error || "Unknown error");
        }
      } catch {
        // Network error — keep polling, don't crash
      }
    };

    poll();
    intervalRef.current = setInterval(poll, interval);
  }, [videoId, interval, stopPolling]);

  useEffect(() => {
    if (enabled) {
      startPolling();
    } else {
      stopPolling();
      setState({ status: "idle", message: null, error: null });
    }
    return stopPolling;
  }, [enabled, startPolling, stopPolling]);

  const reset = useCallback(() => {
    stopPolling();
    setState({ status: "idle", message: null, error: null });
  }, [stopPolling]);

  return { ...state, reset, isPolling: !!intervalRef.current };
}

interface UseTaskWatcherOptions {
  videoId: string;
  interval?: number;
  /** Fired on the running→completed transition (only for work observed live). */
  onComplete?: (message?: string | null) => void;
  /** Fired on the running→failed transition. */
  onFailed?: (error: string) => void;
  /** Fired on every poll while work is running. */
  onProgress?: (message: string | null) => void;
}

/**
 * Always-on task watcher. Unlike useTaskPoller (armed by the surface that
 * STARTED the work), this watches the video's single task slot continuously —
 * so one banner can show progress and offer Stop no matter which button,
 * browser tab, or per-scene control kicked the work off. The task endpoint
 * keeps returning the LAST task's terminal status, so completion/failure only
 * fires on a transition observed in this session — never from stale history.
 */
export function useTaskWatcher({ videoId, interval = 3000, onComplete, onFailed, onProgress }: UseTaskWatcherOptions) {
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // C28: "via agent" attribution — mirrors `message`'s lifecycle exactly
  // (set while active, cleared to null once the task isn't running/pending
  // — an agent's OWN claim is released the moment the run ends, so there is
  // nothing meaningful to show once the task is done anyway).
  const [viaAgent, setViaAgent] = useState<string | null>(null);
  // UX-2 (2026-07-30): structured task_type ("roster_prefetch" for both the
  // manual roster re-check and the automatic post-research sweep) — mirrors
  // message/viaAgent's lifecycle (set while active, cleared once the task
  // isn't running/pending) so a consumer can key off it instead of parsing
  // `message` text.
  const [taskType, setTaskType] = useState<string | null>(null);
  const wasRunningRef = useRef(false);
  // Bumped by markStarted so a poll response that was ALREADY in flight when
  // new work started can't be misread as "the new work finished" (which would
  // fire onComplete — and any queued chain stage — before the work even ran).
  const epochRef = useRef(0);
  const onCompleteRef = useRef(onComplete);
  const onFailedRef = useRef(onFailed);
  const onProgressRef = useRef(onProgress);
  onCompleteRef.current = onComplete;
  onFailedRef.current = onFailed;
  onProgressRef.current = onProgress;

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const epoch = epochRef.current;
        const task = await getPipelineTaskStatus(videoId);
        if (cancelled || epoch !== epochRef.current) return;
        const active = task.status === "running" || task.status === "pending";
        if (active) {
          wasRunningRef.current = true;
          setRunning(true);
          setMessage(task.message ?? null);
          setViaAgent(task.via_agent ?? null);
          setTaskType(task.task_type ?? null);
          onProgressRef.current?.(task.message ?? null);
        } else {
          if (wasRunningRef.current) {
            wasRunningRef.current = false;
            if (task.status === "failed") onFailedRef.current?.(task.error || "Unknown error");
            else onCompleteRef.current?.(task.message);
          }
          setRunning(false);
          setMessage(null);
          setViaAgent(null);
          setTaskType(null);
        }
      } catch {
        // Network blip — keep watching
      }
    };
    poll();
    const id = setInterval(poll, interval);
    return () => { cancelled = true; clearInterval(id); };
  }, [videoId, interval]);

  /** Optimistic arm: call right after starting work so the UI flips instantly. */
  const markStarted = useCallback(() => {
    epochRef.current += 1; // invalidate any poll already in flight
    wasRunningRef.current = true;
    setRunning(true);
    // Optimistic arm has no way to know attribution yet (it fires the instant
    // a LOCAL click starts work, before the first poll lands) — clear any
    // stale agent name from a previous run rather than showing it briefly
    // for a run this browser tab itself just started.
    setViaAgent(null);
    // Optimistic arm doesn't know task_type yet either — clear any stale
    // value from a previous run for the same reason viaAgent is cleared.
    setTaskType(null);
  }, []);

  return { running, message, viaAgent, taskType, markStarted };
}

export interface TaskWatcherHandlers {
  onComplete?: (message?: string | null) => void;
  onFailed?: (error: string) => void;
  onProgress?: (message: string | null) => void;
}

/**
 * Bridge exposed by the ONE page-level useTaskWatcher (see
 * pipeline/[videoId]/page.tsx) so TaskFailureBanner and every tab can react
 * to the video's single task slot without each mounting its own 3s poll
 * against the same getPipelineTaskStatus endpoint (S9-1/C19a — this used to
 * be 2-3 concurrent identical pollers: the old always-on GuidedNextStep
 * (U5: removed, replaced by TaskFailureBanner) + the active tab + sometimes
 * page.tsx's own).
 */
export interface TaskWatcherBridge {
  running: boolean;
  message: string | null;
  /** C28: the agent's display name when the running task's claim is
   * agent-held, null otherwise — read directly off the bridge (same pattern
   * `running` already uses), not threaded through useSharedTaskWatcher's
   * return value. */
  viaAgent: string | null;
  /** UX-2 (2026-07-30): structured task_type of the currently-running task
   * (e.g. "roster_prefetch"), null when idle or unset — same
   * always-available-off-the-bridge pattern as `running`/`viaAgent`, so a
   * consumer (RosterStagePanel.tsx) can detect "a roster sweep is running"
   * without parsing `message` text, whether the sweep was started manually
   * or dispatched automatically after research. */
  taskType: string | null;
  markStarted: () => void;
  /** Register handlers against the one shared poll stream; returns the
   * unsubscribe fn. A consumer only hears about completions/failures while
   * subscribed — see useSharedTaskWatcher's `enabled` gate below, which
   * mirrors the old per-tab useTaskPoller `enabled` semantics exactly. */
  subscribe: (handlers: TaskWatcherHandlers) => () => void;
}

/**
 * Drop-in replacement for a tab's own useTaskPoller: same enabled-gated
 * on{Complete,Failed,Progress} contract (a tab only reacts to a task it
 * believes it started, via its own local `taskRunning`/`enabled` flag), but
 * it rides the page's ONE shared watcher instead of opening a second 3s
 * interval against the same endpoint. `enabled` defaults to true for
 * always-on consumers (TaskFailureBanner, ScenesWorkspaceTab) that watch
 * whatever holds the video's task slot regardless of who started it.
 */
export function useSharedTaskWatcher({
  bridge,
  enabled = true,
  onComplete,
  onFailed,
  onProgress,
}: {
  bridge: TaskWatcherBridge;
  enabled?: boolean;
  onComplete?: (message?: string | null) => void;
  onFailed?: (error: string) => void;
  onProgress?: (message: string | null) => void;
}): { message: string | null } {
  const onCompleteRef = useRef(onComplete);
  const onFailedRef = useRef(onFailed);
  const onProgressRef = useRef(onProgress);
  onCompleteRef.current = onComplete;
  onFailedRef.current = onFailed;
  onProgressRef.current = onProgress;

  useEffect(() => {
    if (!enabled) return;
    return bridge.subscribe({
      onComplete: (msg) => onCompleteRef.current?.(msg),
      onFailed: (err) => onFailedRef.current?.(err),
      onProgress: (msg) => onProgressRef.current?.(msg),
    });
  }, [bridge, enabled]);

  return { message: bridge.message };
}
