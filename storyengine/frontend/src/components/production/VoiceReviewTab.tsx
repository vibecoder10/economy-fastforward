"use client";

import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Pause, SkipBack, SkipForward, Shuffle, Volume2, Check, Loader2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { MiniWaveform } from "@/components/ui/MiniWaveform";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { ActionButton } from "@/components/ui/ActionButton";
import { getVideoScript, getVideoAssets, approveAsset, runImageVariants, runImageForSegment } from "@/lib/api";
import type { ScriptScene as ApiScriptScene, Asset } from "@/lib/api";
import type { Video, VoiceSegment } from "@/lib/types";

interface VoiceReviewTabProps {
  video: Video;
}

// Generate consistent waveform bars for the main waveform
function generateWaveformBars(count: number): number[] {
  const bars: number[] = [];
  for (let i = 0; i < count; i++) {
    const pos = i / count;
    const envelope = Math.sin(pos * Math.PI) * 0.6 + 0.2;
    const noise = Math.sin(i * 7.3) * 0.15 + Math.sin(i * 13.1) * 0.1;
    bars.push(Math.max(0.05, Math.min(1, envelope + noise)));
  }
  return bars;
}

interface VoiceSegmentData extends VoiceSegment {
  voiceOverUrl: string | null | undefined;
  voiceStatus: string | null | undefined;
}

export function VoiceReviewTab({ video }: VoiceReviewTabProps) {
  const queryClient = useQueryClient();
  const { data: scriptScenes, isLoading: loadingScripts } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });
  const { data: assets, isLoading: loadingAssets } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });

  const computedSegments = useMemo<VoiceSegmentData[]>(() => {
    if (!scriptScenes || !assets) return [];
    return scriptScenes.map((scene) => ({
      id: scene.id,
      sceneNumber: scene.scene || 0,
      narrationText: scene.scene_text || "",
      duration: `${Math.round((scene.scene_text || "").split(/\s+/).length / 2.5)}s`,
      voiceOverUrl: scene.voice_over_url,
      voiceStatus: scene.voice_status,
      panels: assets
        .filter((a) => a.scene === scene.scene)
        .sort((a, b) => (a.image_index || 0) - (b.image_index || 0))
        .slice(0, 9)
        .map((a) => ({ id: a.id, imageUrl: a.image_url || undefined })),
      approved: scene.voice_status === "Done",
      selectedPanel: undefined,
    }));
  }, [scriptScenes, assets]);

  const [segments, setSegments] = useState<VoiceSegmentData[]>([]);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playAll, setPlayAll] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState("1.0x");
  const [volume, setVolume] = useState(75);
  const [activeSegment, setActiveSegment] = useState<string | null>(null);
  const [isApprovingScene, setIsApprovingScene] = useState(false);
  const [isRegeneratingGrid, setIsRegeneratingGrid] = useState(false);
  const [isRegeneratingPanel, setIsRegeneratingPanel] = useState(false);

  // Audio refs for per-segment playback
  const audioRefs = useRef<Record<string, HTMLAudioElement>>({});

  // Sync computed segments into local state
  useEffect(() => {
    if (computedSegments.length > 0 && segments.length === 0) {
      setSegments(computedSegments);
    }
  }, [computedSegments, segments.length]);

  const waveformBars = useMemo(() => generateWaveformBars(120), []);

  const approvedCount = segments.filter((s) => s.approved).length;
  const totalSegments = segments.length;

  const selectPanel = (segmentId: string, panelIdx: number) => {
    setSegments((prev) =>
      prev.map((s) => (s.id === segmentId ? { ...s, selectedPanel: panelIdx } : s))
    );
  };

  const approveSegment = (segmentId: string) => {
    setSegments((prev) =>
      prev.map((s) => (s.id === segmentId ? { ...s, approved: true } : s))
    );
  };

  const handleApproveScene = useCallback(async () => {
    if (!activeSegment && segments.length === 0) return;
    // Approve the currently active segment, or the first unapproved one
    const target = activeSegment
      ? segments.find((s) => s.id === activeSegment)
      : segments.find((s) => !s.approved);
    if (!target) return;

    setIsApprovingScene(true);
    try {
      // Approve all panels for this segment
      for (const panel of target.panels) {
        if (panel.id) {
          await approveAsset(panel.id);
        }
      }
      approveSegment(target.id);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } finally {
      setIsApprovingScene(false);
    }
  }, [activeSegment, segments, video.id, queryClient]);

  const handleRegenerateGrid = useCallback(async () => {
    const target = activeSegment
      ? segments.find((s) => s.id === activeSegment)
      : segments.find((s) => !s.approved);
    if (!target) return;

    setIsRegeneratingGrid(true);
    try {
      await runImageVariants(video.id, target.sceneNumber, 1, 9);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } finally {
      setIsRegeneratingGrid(false);
    }
  }, [activeSegment, segments, video.id, queryClient]);

  const handleRegeneratePanel = useCallback(async () => {
    const target = activeSegment
      ? segments.find((s) => s.id === activeSegment)
      : segments.find((s) => !s.approved);
    if (!target || target.selectedPanel === undefined) return;

    setIsRegeneratingPanel(true);
    try {
      await runImageForSegment(video.id, target.sceneNumber, target.selectedPanel + 1);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } finally {
      setIsRegeneratingPanel(false);
    }
  }, [activeSegment, segments, video.id, queryClient]);

  // Play/pause a specific segment's voice-over
  const toggleSegmentPlay = useCallback(
    (segmentId: string, voiceOverUrl: string | null | undefined) => {
      // If already active, stop it
      if (activeSegment === segmentId) {
        const audio = audioRefs.current[segmentId];
        if (audio) {
          audio.pause();
          audio.currentTime = 0;
        }
        setActiveSegment(null);
        return;
      }

      // Stop any currently playing segment
      if (activeSegment && audioRefs.current[activeSegment]) {
        audioRefs.current[activeSegment].pause();
        audioRefs.current[activeSegment].currentTime = 0;
      }

      if (!voiceOverUrl) {
        setActiveSegment(null);
        return;
      }

      // Create or reuse audio element
      if (!audioRefs.current[segmentId]) {
        audioRefs.current[segmentId] = new Audio(voiceOverUrl);
        audioRefs.current[segmentId].addEventListener("ended", () => {
          setActiveSegment(null);
        });
      }

      const audio = audioRefs.current[segmentId];
      audio.volume = volume / 100;
      audio.playbackRate = parseFloat(playbackSpeed);
      audio.play().catch(() => {
        // Autoplay blocked or URL invalid
        setActiveSegment(null);
      });
      setActiveSegment(segmentId);
    },
    [activeSegment, volume, playbackSpeed]
  );

  // Update volume on active audio
  useEffect(() => {
    if (activeSegment && audioRefs.current[activeSegment]) {
      audioRefs.current[activeSegment].volume = volume / 100;
    }
  }, [volume, activeSegment]);

  // Update playback speed on active audio
  useEffect(() => {
    if (activeSegment && audioRefs.current[activeSegment]) {
      audioRefs.current[activeSegment].playbackRate = parseFloat(playbackSpeed);
    }
  }, [playbackSpeed, activeSegment]);

  // Playhead position (mock)
  const playheadPct = 22;

  if (loadingScripts || loadingAssets) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--green)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>Loading voice data...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-24">
      {/* Main layout: content + sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
        {/* Left column */}
        <div className="space-y-6">
          {/* Full waveform */}
          <GlassCard className="p-5">
            <div className="relative">
              {/* Waveform visualization */}
              <div className="relative h-24 flex items-center">
                {/* Play button overlay */}
                <button
                  onClick={() => setIsPlaying(!isPlaying)}
                  className="absolute left-0 top-1/2 -translate-y-1/2 z-10 w-8 h-8 rounded-full flex items-center justify-center"
                  style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
                >
                  {isPlaying ? (
                    <Pause size={14} style={{ color: "var(--green)" }} />
                  ) : (
                    <Play size={14} style={{ color: "var(--green)" }} className="ml-0.5" />
                  )}
                </button>

                {/* Waveform bars */}
                <div className="flex-1 ml-12 h-full flex items-center gap-px relative">
                  {waveformBars.map((h, i) => {
                    const pct = (i / waveformBars.length) * 100;
                    const isPast = pct < playheadPct;
                    return (
                      <div
                        key={i}
                        className="flex-1 rounded-sm transition-colors"
                        style={{
                          height: `${h * 100}%`,
                          background: isPast ? "var(--green)" : "rgba(0, 230, 138, 0.25)",
                          minWidth: 2,
                        }}
                      />
                    );
                  })}

                  {/* Playhead */}
                  <div
                    className="absolute top-0 bottom-0 w-0.5"
                    style={{
                      left: `${playheadPct}%`,
                      background: "var(--turquoise)",
                      boxShadow: "0 0 8px var(--turquoise-glow)",
                    }}
                  />
                </div>

                {/* Timestamp */}
                <div className="ml-4 shrink-0">
                  <span className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>
                    01:23 <span style={{ color: "var(--text-tertiary)" }}>/ 14:32</span>
                  </span>
                </div>
              </div>

              {/* Segment dividers */}
              <div className="flex mt-3 ml-12 gap-0">
                {segments.map((seg, i) => (
                  <div
                    key={seg.id}
                    className="flex-1 text-center py-1"
                    style={{
                      borderTop: "1px solid var(--border-subtle)",
                      borderRight: i < segments.length - 1 ? "1px dashed var(--border-subtle)" : "none",
                    }}
                  >
                    <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                      S-{String(seg.sceneNumber).padStart(2, "0")}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </GlassCard>

          {/* Scene review cards */}
          {segments.map((segment) => (
            <GlassCard
              key={segment.id}
              className="p-5"
              style={{
                borderColor: segment.approved ? "rgba(0, 230, 138, 0.2)" : activeSegment === segment.id ? "rgba(0, 212, 170, 0.3)" : undefined,
              }}
            >
              <div className="flex gap-5 flex-col md:flex-row">
                {/* Left: narration + mini waveform */}
                <div className="md:w-2/5 space-y-3">
                  <div className="flex items-center gap-2">
                    <SegmentBadge
                      label={`S-${String(segment.sceneNumber).padStart(2, "0")}`}
                      color={segment.approved ? "var(--green)" : undefined}
                    />
                    {segment.approved && (
                      <StatusPill label="Approved" color="green" size="sm" />
                    )}
                  </div>

                  <p className="text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>
                    {segment.narrationText}
                  </p>

                  {/* Mini waveform + play */}
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => toggleSegmentPlay(segment.id, segment.voiceOverUrl)}
                      className="w-7 h-7 rounded-full flex items-center justify-center shrink-0"
                      style={{
                        background: segment.voiceOverUrl ? "var(--green)" : "var(--bg-surface)",
                        color: "var(--bg-void)",
                        opacity: segment.voiceOverUrl ? 1 : 0.4,
                      }}
                    >
                      {activeSegment === segment.id ? <Pause size={12} /> : <Play size={12} className="ml-0.5" />}
                    </button>
                    <MiniWaveform color="var(--green)" width={180} height={24} bars={35} />
                    <span className="text-xs font-mono shrink-0" style={{ color: "var(--text-tertiary)" }}>
                      {segment.duration}
                    </span>
                  </div>
                </div>

                {/* Right: 3x3 grid + selectors */}
                <div className="flex-1">
                  {/* 3x3 contact sheet */}
                  <div className="grid grid-cols-3 gap-1.5">
                    {segment.panels.map((panel, panelIdx) => {
                      const isSelected = segment.selectedPanel === panelIdx;
                      const isApproved = segment.approved && isSelected;
                      return (
                        <button
                          key={panel.id}
                          onClick={() => selectPanel(segment.id, panelIdx)}
                          className="aspect-video rounded relative overflow-hidden transition-all"
                          style={{
                            background: "var(--bg-elevated)",
                            border: isSelected
                              ? "2px solid var(--turquoise)"
                              : "1px solid var(--border-subtle)",
                            opacity: segment.approved && !isSelected ? 0.3 : 1,
                          }}
                        >
                          {panel.imageUrl ? (
                            <img src={panel.imageUrl} alt={`Panel ${panelIdx + 1}`} className="absolute inset-0 w-full h-full object-cover" />
                          ) : (
                            <>
                              {/* Grid pattern */}
                              <svg className="absolute inset-0 w-full h-full opacity-15">
                                <defs>
                                  <pattern id={`vr-${panel.id}`} width="12" height="12" patternUnits="userSpaceOnUse">
                                    <path d="M 12 0 L 0 0 0 12" fill="none" stroke="var(--turquoise)" strokeWidth="0.3" />
                                  </pattern>
                                </defs>
                                <rect width="100%" height="100%" fill={`url(#vr-${panel.id})`} />
                              </svg>

                              {/* X pattern */}
                              <svg className="absolute inset-0 w-full h-full opacity-10">
                                <line x1="0" y1="0" x2="100%" y2="100%" stroke="var(--text-tertiary)" strokeWidth="0.5" />
                                <line x1="100%" y1="0" x2="0" y2="100%" stroke="var(--text-tertiary)" strokeWidth="0.5" />
                              </svg>
                            </>
                          )}

                          {isApproved && (
                            <div className="absolute inset-0 flex items-center justify-center bg-black/40">
                              <div className="w-6 h-6 rounded-full flex items-center justify-center" style={{ background: "var(--turquoise)" }}>
                                <Check size={12} style={{ color: "var(--bg-void)" }} />
                              </div>
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>

                  {/* Numbered radio selectors */}
                  <div className="flex items-center gap-1 mt-2">
                    {segment.panels.map((_, panelIdx) => (
                      <button
                        key={panelIdx}
                        onClick={() => selectPanel(segment.id, panelIdx)}
                        className="flex items-center justify-center text-[10px] font-mono transition-all"
                        style={{
                          width: 22,
                          height: 22,
                          borderRadius: "50%",
                          background: segment.selectedPanel === panelIdx ? "var(--turquoise)" : "transparent",
                          color: segment.selectedPanel === panelIdx ? "var(--bg-void)" : "var(--text-tertiary)",
                          border: `1.5px solid ${segment.selectedPanel === panelIdx ? "var(--turquoise)" : "var(--text-tertiary)"}`,
                        }}
                      >
                        {panelIdx + 1}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </GlassCard>
          ))}
        </div>

        {/* Right sidebar */}
        <div className="space-y-4">
          <GlassCard className="p-5">
            <div className="space-y-4">
              <div>
                <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Total Segments</p>
                <p className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>{totalSegments}</p>
              </div>

              <div>
                <p className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>Approved</p>
                <div className="flex items-center gap-3">
                  <p className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>{approvedCount}</p>
                  <ProgressRing value={totalSegments > 0 ? (approvedCount / totalSegments) * 100 : 0} size={50} color="var(--turquoise)" strokeWidth={4} />
                </div>
              </div>

              <div className="pt-3 space-y-2" style={{ borderTop: "1px solid var(--border-subtle)" }}>
                {[
                  { label: "Voice ID", value: "#0A00E218" },
                  { label: "Model", value: "Nano Banana 2" },
                  { label: "Estimated Cost", value: `$${(totalSegments * 6.42).toFixed(2)}`, color: "var(--green)" },
                ].map((row) => (
                  <div key={row.label}>
                    <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>{row.label}</p>
                    <p className="text-sm font-mono font-medium" style={{ color: row.color || "var(--text-primary)" }}>{row.value}</p>
                  </div>
                ))}
              </div>
            </div>
          </GlassCard>

          <div className="space-y-2">
            <ActionButton
              variant="filled"
              className="w-full"
              onClick={handleApproveScene}
              disabled={isApprovingScene}
            >
              {isApprovingScene ? "Approving..." : "Approve Scene"}
            </ActionButton>
            <button
              className="w-full py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110"
              style={{
                background: "rgba(255, 120, 73, 0.15)",
                color: "var(--orange)",
                border: "1px solid var(--orange)",
                opacity: isRegeneratingGrid ? 0.5 : 1,
              }}
              onClick={handleRegenerateGrid}
              disabled={isRegeneratingGrid}
            >
              {isRegeneratingGrid ? "Regenerating..." : "Regenerate Grid"}
            </button>
            <button
              className="w-full py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110"
              style={{
                background: "rgba(255, 120, 73, 0.15)",
                color: "var(--orange)",
                border: "1px solid var(--orange)",
                opacity: isRegeneratingPanel ? 0.5 : 1,
              }}
              onClick={handleRegeneratePanel}
              disabled={isRegeneratingPanel}
            >
              {isRegeneratingPanel ? "Regenerating..." : "Regenerate Single Panel"}
            </button>
          </div>
        </div>
      </div>

      {/* Bottom transport bar */}
      <div className="fixed bottom-0 left-0 right-0 z-40 md:pl-60">
        <div
          className="mx-auto px-6 py-3 flex items-center justify-between gap-4"
          style={{
            background: "rgba(10, 14, 22, 0.95)",
            borderTop: "1px solid var(--border)",
            backdropFilter: "blur(12px)",
          }}
        >
          {/* Play All toggle */}
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Play All</span>
            <button
              onClick={() => setPlayAll(!playAll)}
              className="w-10 h-5 rounded-full relative transition-all"
              style={{ background: playAll ? "var(--green)" : "var(--bg-surface)" }}
            >
              <div
                className="w-4 h-4 rounded-full absolute top-0.5 transition-all"
                style={{
                  background: playAll ? "var(--bg-void)" : "var(--text-tertiary)",
                  left: playAll ? "calc(100% - 18px)" : "2px",
                }}
              />
            </button>
          </div>

          {/* Playback controls */}
          <div className="flex items-center gap-3">
            <button style={{ color: "var(--text-secondary)" }}>
              <Shuffle size={16} />
            </button>
            <button style={{ color: "var(--text-secondary)" }}>
              <SkipBack size={18} />
            </button>
            <button
              onClick={() => setIsPlaying(!isPlaying)}
              className="w-10 h-10 rounded-full flex items-center justify-center"
              style={{ background: "var(--green)" }}
            >
              {isPlaying ? (
                <Pause size={18} style={{ color: "var(--bg-void)" }} />
              ) : (
                <Play size={18} style={{ color: "var(--bg-void)" }} className="ml-0.5" />
              )}
            </button>
            <button style={{ color: "var(--text-secondary)" }}>
              <SkipForward size={18} />
            </button>

            {/* Speed */}
            <select
              value={playbackSpeed}
              onChange={(e) => setPlaybackSpeed(e.target.value)}
              className="text-xs font-mono px-2 py-1 rounded"
              style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "none" }}
            >
              <option value="0.5x">0.5x</option>
              <option value="0.75x">0.75x</option>
              <option value="1.0x">1.0x</option>
              <option value="1.25x">1.25x</option>
              <option value="1.5x">1.5x</option>
              <option value="2.0x">2.0x</option>
            </select>
          </div>

          {/* Volume */}
          <div className="flex items-center gap-2 shrink-0">
            <Volume2 size={16} style={{ color: "var(--text-secondary)" }} />
            <input
              type="range"
              min={0}
              max={100}
              value={volume}
              onChange={(e) => setVolume(Number(e.target.value))}
              className="w-20 accent-[var(--green)]"
              style={{ accentColor: "var(--green)" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
