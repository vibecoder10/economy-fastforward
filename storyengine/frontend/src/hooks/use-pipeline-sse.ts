"use client";

import { useState, useEffect, useRef, useCallback } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

/** Activity event from the SSE stream (matches backend bot_activity row). */
export interface SSEActivityEvent {
  id: string;
  bot_name: string;
  video_id: string | null;
  video_title: string | null;
  status: string;
  message: string | null;
  cost: number;
  created_at: string | null;
}

/** Stage change event (emitted when a video transitions pipeline stages). */
export interface SSEStageChangeEvent {
  video_id: string;
  video_title: string | null;
  old_status: string;
  new_status: string;
  changed_at: string;
}

export interface UsePipelineSSEOptions {
  /** Set false to disconnect. Default true. */
  enabled?: boolean;
  /** Called for each activity event. */
  onActivity?: (event: SSEActivityEvent) => void;
  /** Called for each stage_change event. */
  onStageChange?: (event: SSEStageChangeEvent) => void;
  /** Called when connection state changes. */
  onConnectionChange?: (connected: boolean) => void;
}

interface SSEState {
  isConnected: boolean;
  lastEvent: SSEActivityEvent | null;
  lastStageChange: SSEStageChangeEvent | null;
  reconnectAttempt: number;
}

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

function getBackoff(attempt: number): number {
  return Math.min(BASE_BACKOFF_MS * Math.pow(2, attempt), MAX_BACKOFF_MS);
}

export function usePipelineSSE(options: UsePipelineSSEOptions = {}) {
  const { enabled = true } = options;
  const [state, setState] = useState<SSEState>({
    isConnected: false,
    lastEvent: null,
    lastStageChange: null,
    reconnectAttempt: 0,
  });

  const onActivityRef = useRef(options.onActivity);
  const onStageChangeRef = useRef(options.onStageChange);
  const onConnectionChangeRef = useRef(options.onConnectionChange);
  onActivityRef.current = options.onActivity;
  onStageChangeRef.current = options.onStageChange;
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

    // Get token for query-param auth (EventSource can't set headers)
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("token") || "dev-token"
        : "dev-token";

    const url = `${API_URL}/api/activity/stream?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      attemptRef.current = 0;
      setState((s) => ({ ...s, isConnected: true, reconnectAttempt: 0 }));
      onConnectionChangeRef.current?.(true);
    };

    // Default message event (activity entries — no named event type)
    es.onmessage = (e) => {
      try {
        const data: SSEActivityEvent = JSON.parse(e.data);
        setState((s) => ({ ...s, lastEvent: data }));
        onActivityRef.current?.(data);
      } catch {
        // Ignore malformed events
      }
    };

    // Named event: stage_change (emitted by backend task 3)
    es.addEventListener("stage_change", ((e: MessageEvent) => {
      try {
        const data: SSEStageChangeEvent = JSON.parse(e.data);
        setState((s) => ({ ...s, lastStageChange: data }));
        onStageChangeRef.current?.(data);
      } catch {
        // Ignore malformed events
      }
    }) as EventListener);

    es.onerror = () => {
      es.close();
      esRef.current = null;
      setState((s) => ({ ...s, isConnected: false }));
      onConnectionChangeRef.current?.(false);

      // Exponential backoff reconnect
      const attempt = attemptRef.current;
      attemptRef.current = attempt + 1;
      const backoff = getBackoff(attempt);
      setState((s) => ({ ...s, reconnectAttempt: attempt + 1 }));

      reconnectTimerRef.current = setTimeout(() => {
        connect();
      }, backoff);
    };
  }, [cleanup]);

  useEffect(() => {
    if (enabled) {
      connect();
    } else {
      cleanup();
      setState({
        isConnected: false,
        lastEvent: null,
        lastStageChange: null,
        reconnectAttempt: 0,
      });
    }
    return cleanup;
  }, [enabled, connect, cleanup]);

  return {
    isConnected: state.isConnected,
    lastEvent: state.lastEvent,
    lastStageChange: state.lastStageChange,
    reconnectAttempt: state.reconnectAttempt,
  };
}
