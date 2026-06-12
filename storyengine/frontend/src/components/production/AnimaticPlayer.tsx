"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Pause, Play } from "lucide-react";
import { getAudioToken } from "@/lib/api";
import { API_URL } from "@/lib/env";

export interface AnimaticPanel {
  /** Display-ready image URL (already proxied) */
  url: string;
  /** The narration sentence this picture illustrates */
  text: string;
}

interface AnimaticPlayerProps {
  videoId: string;
  scene: number;
  panels: AnimaticPanel[];
}

/**
 * The $0 movie: plays the scene's voiceover while stepping through its final
 * pictures, each held for a share of the audio proportional to its sentence's
 * word count. This is the storyboard coming alive BEFORE any clip money is
 * spent — the review tool for "does this scene work?".
 */
export function AnimaticPlayer({ videoId, scene, panels }: AnimaticPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [progress, setProgress] = useState(0); // 0..1
  const [panelIdx, setPanelIdx] = useState(0);

  // Word-count share of the audio per panel → cumulative switch points (0..1).
  const boundaries = useMemo(() => {
    const words = panels.map((p) => Math.max(1, (p.text || "").trim().split(/\s+/).length));
    const total = words.reduce((a, b) => a + b, 0);
    let acc = 0;
    return words.map((w) => (acc += w / total));
  }, [panels]);

  useEffect(() => {
    let cancelled = false;
    getAudioToken(videoId)
      .then(({ token }) => {
        if (!cancelled) setAudioUrl(`${API_URL}/api/videos/${videoId}/audio/${scene}?token=${token}`);
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [videoId, scene]);

  // Preload all panel images once so playback never shows a blank frame.
  useEffect(() => {
    panels.forEach((p) => { const img = new Image(); img.src = p.url; });
  }, [panels]);

  const onTimeUpdate = () => {
    const a = audioRef.current;
    if (!a || !a.duration || !isFinite(a.duration)) return;
    const frac = a.currentTime / a.duration;
    setProgress(frac);
    const idx = boundaries.findIndex((b) => frac < b);
    setPanelIdx(idx === -1 ? panels.length - 1 : idx);
  };

  const toggle = async () => {
    const a = audioRef.current;
    if (!a) return;
    if (playing) {
      a.pause();
      return;
    }
    setLoading(true);
    try {
      if (a.ended) a.currentTime = 0;
      await a.play();
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };

  if (failed || panels.length === 0) return null;

  return (
    <div className="mb-3" style={{ maxWidth: 480 }}>
      <p className="text-[10px] uppercase tracking-wider font-semibold mb-1.5" style={{ color: "var(--turquoise)" }}>
        Watch this scene
      </p>
      <div
        className="relative rounded-xl overflow-hidden cursor-pointer group/animatic"
        style={{ aspectRatio: "16 / 9", background: "var(--bg-elevated)", border: "1px solid rgba(0, 245, 212, 0.2)" }}
        onClick={toggle}
        title={playing ? "Pause" : "Play this scene — pictures + narration"}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={panels[panelIdx]?.url}
          alt={`Scene ${scene}, picture ${panelIdx + 1}`}
          className="w-full h-full object-cover"
          style={{ transition: "opacity 200ms ease" }}
        />
        {/* Caption — the sentence this picture illustrates */}
        {playing && panels[panelIdx]?.text && (
          <div
            className="absolute bottom-0 left-0 right-0 px-3 py-2 text-center"
            style={{ background: "linear-gradient(transparent, rgba(0,0,0,0.85))" }}
          >
            <p className="text-xs font-medium" style={{ color: "#fff", textShadow: "0 1px 2px rgba(0,0,0,0.8)" }}>
              {panels[panelIdx].text}
            </p>
          </div>
        )}
        {/* Center play/pause */}
        <div
          className={`absolute inset-0 flex items-center justify-center transition-opacity ${playing ? "opacity-0 group-hover/animatic:opacity-100" : "opacity-100"}`}
          style={{ background: playing ? "rgba(0,0,0,0.25)" : "rgba(0,0,0,0.35)" }}
        >
          <div
            className="w-14 h-14 rounded-full flex items-center justify-center"
            style={{ background: "rgba(0, 245, 212, 0.92)", color: "var(--bg-void)", boxShadow: "0 4px 20px rgba(0,0,0,0.4)" }}
          >
            {loading ? <Loader2 size={24} className="animate-spin" /> : playing ? <Pause size={24} /> : <Play size={24} className="ml-0.5" />}
          </div>
        </div>
        {/* Progress bar */}
        <div className="absolute bottom-0 left-0 right-0 h-1" style={{ background: "rgba(255,255,255,0.15)" }}>
          <div className="h-full" style={{ width: `${progress * 100}%`, background: "var(--turquoise)", transition: "width 200ms linear" }} />
        </div>
        {/* Panel counter */}
        <span
          className="absolute top-2 right-2 text-[10px] font-mono px-1.5 py-0.5 rounded"
          style={{ background: "rgba(0,0,0,0.6)", color: "rgba(255,255,255,0.85)" }}
        >
          {panelIdx + 1}/{panels.length}
        </span>
      </div>
      {audioUrl && (
        <audio
          ref={audioRef}
          src={audioUrl}
          preload="metadata"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => { setPlaying(false); setProgress(0); setPanelIdx(0); }}
          onTimeUpdate={onTimeUpdate}
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}
