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
          onProgressRef.current?.(task.message ?? null);
        } else {
          if (wasRunningRef.current) {
            wasRunningRef.current = false;
            if (task.status === "failed") onFailedRef.current?.(task.error || "Unknown error");
            else onCompleteRef.current?.(task.message);
          }
          setRunning(false);
          setMessage(null);
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
  }, []);

  return { running, message, markStarted };
}

export interface TaskWatcherHandlers {
  onComplete?: (message?: string | null) => void;
  onFailed?: (error: string) => void;
  onProgress?: (message: string | null) => void;
}

/**
 * Bridge exposed by the ONE page-level useTaskWatcher (see
 * pipeline/[videoId]/page.tsx) so GuidedNextStep and every tab can react to
 * the video's single task slot without each mounting its own 3s poll against
 * the same getPipelineTaskStatus endpoint (S9-1/C19a — this used to be 2-3
 * concurrent identical pollers: GuidedNextStep + the active tab + sometimes
 * page.tsx's own).
 */
export interface TaskWatcherBridge {
  running: boolean;
  message: string | null;
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
 * always-on consumers (GuidedNextStep, ScenesWorkspaceTab) that watch
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
