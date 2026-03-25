"use client";

import { useState, useRef, useEffect } from "react";
import { Play, Pause, RotateCcw } from "lucide-react";

interface VoicePlayerProps {
  audioUrl: string;
  onRedo?: () => void;
  redoLoading?: boolean;
}

export function VoicePlayer({ audioUrl, onRedo, redoLoading }: VoicePlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTimeUpdate = () => {
      setCurrentTime(audio.currentTime);
      setProgress(audio.duration ? (audio.currentTime / audio.duration) * 100 : 0);
    };
    const onLoaded = () => setDuration(audio.duration);
    const onEnded = () => setPlaying(false);
    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("loadedmetadata", onLoaded);
    audio.addEventListener("ended", onEnded);
    return () => {
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("loadedmetadata", onLoaded);
      audio.removeEventListener("ended", onEnded);
    };
  }, [audioUrl]);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) { audio.pause(); } else { audio.play(); }
    setPlaying(!playing);
  };

  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const audio = audioRef.current;
    if (!audio || !audio.duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    audio.currentTime = pct * audio.duration;
  };

  const fmt = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  return (
    <div
      className="flex items-center gap-2 rounded-lg px-3 py-2"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <audio ref={audioRef} src={audioUrl} preload="metadata" />
      <button
        onClick={togglePlay}
        className="flex items-center justify-center rounded-full"
        style={{ width: 28, height: 28, background: "#1A8A7A", color: "#fff", border: "none", flexShrink: 0 }}
      >
        {playing ? <Pause size={12} /> : <Play size={12} style={{ marginLeft: 1 }} />}
      </button>
      <div className="flex-1 cursor-pointer" onClick={seek}>
        <div className="h-1 rounded-full" style={{ background: "var(--border)" }}>
          <div className="h-full rounded-full transition-all" style={{ width: `${progress}%`, background: "#1A8A7A" }} />
        </div>
      </div>
      <span className="text-xs tabular-nums" style={{ color: "var(--text-muted)", flexShrink: 0 }}>
        {fmt(currentTime)} / {fmt(duration)}
      </span>
      {onRedo && (
        <button
          onClick={onRedo}
          disabled={redoLoading}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded"
          style={{
            background: "var(--bg-card-hover)",
            border: "1px solid var(--border)",
            color: "var(--text-muted)",
            opacity: redoLoading ? 0.5 : 1,
          }}
        >
          <RotateCcw size={10} /> Redo
        </button>
      )}
    </div>
  );
}
