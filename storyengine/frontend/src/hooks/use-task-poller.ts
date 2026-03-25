"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { getPipelineTaskStatus, TaskStatus } from "@/lib/api";

interface UseTaskPollerOptions {
  videoId: string;
  enabled: boolean;
  interval?: number;
  onComplete?: () => void;
  onFailed?: (error: string) => void;
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
}: UseTaskPollerOptions) {
  const [state, setState] = useState<TaskPollerState>({
    status: "idle",
    message: null,
    error: null,
  });
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onCompleteRef = useRef(onComplete);
  const onFailedRef = useRef(onFailed);
  onCompleteRef.current = onComplete;
  onFailedRef.current = onFailed;

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

        if (task.status === "completed") {
          stopPolling();
          onCompleteRef.current?.();
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
