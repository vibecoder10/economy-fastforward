"use client";

import { useState, useEffect } from "react";
import { getAudioToken } from "@/lib/api";
import { API_URL } from "@/lib/env";
import { VoicePlayer } from "@/components/video-detail/voice-player";

/**
 * Harvested out of ScenesWorkspaceTab.tsx (DIRECTOR-CHAT-PLAN.md Task 0.2).
 * Fetches a short-lived audio token, then renders VoicePlayer with scoped URL
 */
export function SecureAudioPlayer({ videoId, scene }: { videoId: string; scene: number }) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getAudioToken(videoId).then(({ token }) => {
      // API_URL, not window.location:8001 — the old guess produced an
      // unreachable port in prod and every player rendered dead at 0:00.
      if (!cancelled) setAudioUrl(`${API_URL}/api/videos/${videoId}/audio/${scene}?token=${token}`);
    }).catch(() => {
      if (!cancelled) setFailed(true);
    });
    return () => { cancelled = true; };
  }, [videoId, scene]);
  if (failed) return null;
  if (!audioUrl) return <p className="text-[10px] mb-3" style={{ color: "var(--text-tertiary)" }}>Loading audio...</p>;
  return <div className="mb-3"><VoicePlayer audioUrl={audioUrl} /></div>;
}
