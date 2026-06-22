"use client";

import { useState, useEffect, useRef, useCallback } from "react";

import { API_URL } from "@/lib/env";

/** Stage change event — a video transitioned between pipeline stages. */
export interface SSEStageChangeEvent {
  video_id: string;
  video_title: string | null;
  current_status: string;
  /** Plain-English progress state (one of the 5 chat-UI states). */
  friendly?: string | null;
  from_status: string;
  to_status: string;
  triggered_by: string | null;
  cost: number | null;
  duration_seconds: number | null;
  error_message: string | null;
  created_at: string | null;
}

/** Task progress event — background task status update. */
export interface SSETaskProgressEvent {
  video_id: string;
  status: "idle" | "running" | "completed" | "failed";
  message: string | null;
  error: string | null;
}

export interface UsePipelineSSEOptions {
  /** Set false to disconnect. Default true. */
  enabled?: boolean;
  /** Filter events for a specific video. Omit for all videos. */
  videoId?: string;
  /** Called for each stage_change event. */
  onStageChange?: (event: SSEStageChangeEvent) => void;
  /** Called for each task_progress event. */
  onTaskProgress?: (event: SSETaskProgressEvent) => void;
  /** Called when connection state changes. */
  onConnectionChange?: (connected: boolean) => void;
}

interface SSEState {
  isConnected: boolean;
  lastStageChange: SSEStageChangeEvent | null;
  lastTaskProgress: SSETaskProgressEvent | null;
  reconnectAttempt: number;
}

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

function getBackoff(attempt: number): number {
  return Math.min(BASE_BACKOFF_MS * Math.pow(2, attempt), MAX_BACKOFF_MS);
}

export function usePipelineSSE(options: UsePipelineSSEOptions = {}) {
  const { enabled = true, videoId } = options;
  const [state, setState] = useState<SSEState>({
    isConnected: false,
    lastStageChange: null,
    lastTaskProgress: null,
    reconnectAttempt: 0,
  });

  const onStageChangeRef = useRef(options.onStageChange);
  const onTaskProgressRef = useRef(options.onTaskProgress);
  const onConnectionChangeRef = useRef(options.onConnectionChange);
  onStageChangeRef.current = options.onStageChange;
  onTaskProgressRef.current = options.onTaskProgress;
  onConnectionChangeRef.current = options.onConnectionChange;

  const esRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);

  const cleanup = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    cleanup();

    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("token") || "dev-token"
        : "dev-token";

    let url = `${API_URL}/api/pipeline/stream?token=${encodeURIComponent(token)}`;
    if (videoId) {
      url += `&video_id=${encodeURIComponent(videoId)}`;
    }

    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      attemptRef.current = 0;
      setState((s) => ({ ...s, isConnected: true, reconnectAttempt: 0 }));
      onConnectionChangeRef.current?.(true);
    };

    es.addEventListener("stage_change", ((e: MessageEvent) => {
      try {
        const data: SSEStageChangeEvent = JSON.parse(e.data);
        setState((s) => ({ ...s, lastStageChange: data }));
        onStageChangeRef.current?.(data);
      } catch {
        // Ignore malformed events
      }
    }) as EventListener);

    es.addEventListener("task_progress", ((e: MessageEvent) => {
      try {
        const data: SSETaskProgressEvent = JSON.parse(e.data);
        setState((s) => ({ ...s, lastTaskProgress: data }));
        onTaskProgressRef.current?.(data);
      } catch {
        // Ignore malformed events
      }
    }) as EventListener);

    es.onerror = () => {
      es.close();
      esRef.current = null;
      setState((s) => ({ ...s, isConnected: false }));
      onConnectionChangeRef.current?.(false);

      const attempt = attemptRef.current;
      attemptRef.current = attempt + 1;
      const backoff = getBackoff(attempt);
      setState((s) => ({ ...s, reconnectAttempt: attempt + 1 }));

      reconnectTimerRef.current = setTimeout(() => {
        connect();
      }, backoff);
    };
  }, [cleanup, videoId]);

  useEffect(() => {
    if (enabled) {
      connect();
    } else {
      cleanup();
      setState({
        isConnected: false,
        lastStageChange: null,
        lastTaskProgress: null,
        reconnectAttempt: 0,
      });
    }
    return cleanup;
  }, [enabled, connect, cleanup]);

  return {
    isConnected: state.isConnected,
    lastStageChange: state.lastStageChange,
    lastTaskProgress: state.lastTaskProgress,
    reconnectAttempt: state.reconnectAttempt,
  };
}
