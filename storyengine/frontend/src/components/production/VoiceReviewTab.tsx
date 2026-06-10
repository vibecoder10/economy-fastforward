"use client";

import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Play, Pause, SkipBack, SkipForward, Volume2,
  Check, Loader2, Mic,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { MiniWaveform } from "@/components/ui/MiniWaveform";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { ActionButton } from "@/components/ui/ActionButton";
import { getVideoScript, getVideoAssets, advanceVideo, runPipelineStage, clearStaleTask } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import type { VideoDetail, ScriptScene as ApiScriptScene, Asset } from "@/lib/api";
import { StopGenerationButton } from "@/components/production/StopGenerationButton";

interface VoiceReviewTabProps {
  video: VideoDetail & { id: string; title?: string; status?: string };
}

interface SegmentData {
  id: string;
  sceneNumber: number;
  narrationText: string;
  duration: string;
  voiceOverUrl: string | null;
  voiceStatus: string | null;
  approved: boolean;
  storyboards: (string | null)[];
}

export function VoiceReviewTab({ video }: VoiceReviewTabProps) {
  const queryClient = useQueryClient();

  const { data: scriptScenes, isLoading: loadingScripts } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });

  const { data: assets } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });

  const segments = useMemo<SegmentData[]>(() => {
    if (!scriptScenes) return [];
    return scriptScenes.map((scene) => ({
      id: scene.id,
      sceneNumber: scene.scene || 0,
      narrationText: scene.scene_text || "",
      duration: `${Math.round((scene.scene_text || "").split(/\s+/).length / 2.5)}s`,
      voiceOverUrl: scene.voice_over_url || null,
      voiceStatus: scene.voice_status || null,
      approved: scene.voice_status === "Done" || scene.voice_status === "Finished",
      storyboards: [
        scene.storyboard_1_url || null,
        scene.storyboard_2_url || null,
        scene.storyboard_3_url || null,
      ],
    }));
  }, [scriptScenes]);

  const [approvedIds, setApprovedIds] = useState<Set<string>>(new Set());
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [approvingAll, setApprovingAll] = useState(false);
  const [activeSegment, setActiveSegment] = useState<string | null>(null);
  const [volume, setVolume] = useState(75);
  const [playbackSpeed, setPlaybackSpeed] = useState("1.0x");
  const audioRefs = useRef<Record<string, HTMLAudioElement>>({});
  const [isGeneratingVoice, setIsGeneratingVoice] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: taskRunning,
    interval: 3000,
    onComplete: () => {
      setTaskRunning(false);
      setIsGeneratingVoice(false);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setIsGeneratingVoice(false);
      alert(`Voice generation failed: ${error}`);
    },
  });

  const handleGenerateVoice = useCallback(async () => {
    setIsGeneratingVoice(true);
    try {
      await runPipelineStage(video.id, "voice");
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "voice");
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          alert(`Voice generation failed: ${(retryErr as Error).message}`);
        }
      } else {
        alert(`Voice generation failed: ${message}`);
      }
      setIsGeneratingVoice(false);
    }
  }, [video.id]);

  // Seed approved set from data
  useEffect(() => {
    if (segments.length > 0) {
      const alreadyApproved = new Set<string>();
      for (const seg of segments) {
        if (seg.approved) alreadyApproved.add(seg.id);
      }
      setApprovedIds((prev) => {
        const merged = new Set(prev);
        for (const id of alreadyApproved) merged.add(id);
        return merged;
      });
    }
  }, [segments]);

  const hasVoice = segments.some((s) => s.voiceOverUrl);
  const approvedCount = segments.filter((s) => approvedIds.has(s.id)).length;
  const totalSegments = segments.length;
  const allApproved = totalSegments > 0 && approvedCount === totalSegments;

  const toggleSegmentPlay = useCallback(
    (segmentId: string, voiceOverUrl: string | null) => {
      if (activeSegment === segmentId) {
        const audio = audioRefs.current[segmentId];
        if (audio) { audio.pause(); audio.currentTime = 0; }
        setActiveSegment(null);
        return;
      }

      // Stop any currently playing
      if (activeSegment && audioRefs.current[activeSegment]) {
        audioRefs.current[activeSegment].pause();
        audioRefs.current[activeSegment].currentTime = 0;
      }

      if (!voiceOverUrl) { setActiveSegment(null); return; }

      if (!audioRefs.current[segmentId]) {
        audioRefs.current[segmentId] = new Audio(voiceOverUrl);
        audioRefs.current[segmentId].addEventListener("ended", () => {
          setActiveSegment(null);
        });
      }

      const audio = audioRefs.current[segmentId];
      audio.volume = volume / 100;
      audio.playbackRate = parseFloat(playbackSpeed);
      audio.play().catch(() => setActiveSegment(null));
      setActiveSegment(segmentId);
    },
    [activeSegment, volume, playbackSpeed],
  );

  useEffect(() => {
    if (activeSegment && audioRefs.current[activeSegment]) {
      audioRefs.current[activeSegment].volume = volume / 100;
    }
  }, [volume, activeSegment]);

  useEffect(() => {
    if (activeSegment && audioRefs.current[activeSegment]) {
      audioRefs.current[activeSegment].playbackRate = parseFloat(playbackSpeed);
    }
  }, [playbackSpeed, activeSegment]);

  const handleApproveScene = useCallback(async (segmentId: string) => {
    setApprovingId(segmentId);
    try {
      // Approve by advancing pipeline; voice approval is implicit
      setApprovedIds((prev) => new Set(prev).add(segmentId));
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    } catch {
      // revert
      setApprovedIds((prev) => {
        const next = new Set(prev);
        next.delete(segmentId);
        return next;
      });
    } finally {
      setApprovingId(null);
    }
  }, [video.id, queryClient]);

  const handleApproveAll = useCallback(async () => {
    setApprovingAll(true);
    try {
      await advanceVideo(video.id);
      const allIds = new Set(segments.map((s) => s.id));
      setApprovedIds(allIds);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    } catch {
      // silent
    } finally {
      setApprovingAll(false);
    }
  }, [video.id, segments, queryClient]);

  const playPrev = useCallback(() => {
    if (!segments.length) return;
    const idx = segments.findIndex((s) => s.id === activeSegment);
    const prevIdx = idx > 0 ? idx - 1 : segments.length - 1;
    toggleSegmentPlay(segments[prevIdx].id, segments[prevIdx].voiceOverUrl);
  }, [segments, activeSegment, toggleSegmentPlay]);

  const playNext = useCallback(() => {
    if (!segments.length) return;
    const idx = segments.findIndex((s) => s.id === activeSegment);
    const nextIdx = idx < segments.length - 1 ? idx + 1 : 0;
    toggleSegmentPlay(segments[nextIdx].id, segments[nextIdx].voiceOverUrl);
  }, [segments, activeSegment, toggleSegmentPlay]);

  if (loadingScripts) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--green)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>Loading voice data...</span>
      </div>
    );
  }

  if (!hasVoice && segments.length === 0) {
    return (
      <GlassCard className="p-12 text-center">
        <Mic size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          Voice Not Generated Yet
        </p>
        <p className="text-sm mb-6" style={{ color: "var(--text-tertiary)" }}>
          The script must be completed before voice generation can begin.
          Current stage: <span style={{ color: "var(--turquoise)" }}>{(video.status || "").replace(/_/g, " ")}</span>
        </p>
        <div className="flex items-center justify-center gap-2">
          <ActionButton
            variant="filled"
            icon={(isGeneratingVoice || taskRunning) ? Loader2 : Mic}
            onClick={handleGenerateVoice}
            disabled={isGeneratingVoice || taskRunning}
          >
            {taskRunning ? (taskMessage || "Generating Voice...") : isGeneratingVoice ? "Starting..." : "Generate Voice"}
          </ActionButton>
          <StopGenerationButton videoId={video.id} running={taskRunning} />
        </div>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-6 pb-24">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
        {/* Left column */}
        <div className="space-y-4">
          {/* Scene review cards */}
          {segments.map((segment) => {
            const isApproved = approvedIds.has(segment.id);
            const isApproving = approvingId === segment.id;
            const hasStoryboards = segment.storyboards.some(Boolean);

            return (
              <GlassCard
                key={segment.id}
                className="p-5"
                style={{
                  borderColor: isApproved
                    ? "rgba(0, 230, 138, 0.2)"
                    : activeSegment === segment.id
                      ? "rgba(0, 212, 170, 0.3)"
                      : undefined,
                }}
              >
                <div className="flex gap-5 flex-col md:flex-row">
                  {/* Left: narration + mini waveform */}
                  <div className="md:w-3/5 space-y-3">
                    <div className="flex items-center gap-2">
                      <SegmentBadge
                        label={`S-${String(segment.sceneNumber).padStart(2, "0")}`}
                        color={isApproved ? "var(--green)" : undefined}
                      />
                      {isApproved ? (
                        <StatusPill label="Approved" color="green" size="sm" />
                      ) : (
                        <StatusPill label="Pending" color="orange" size="sm" />
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

                    {/* Approve button per segment */}
                    {!isApproved && (
                      <button
                        onClick={() => handleApproveScene(segment.id)}
                        disabled={isApproving}
                        className="text-[11px] px-3 py-1.5 rounded-lg transition-all hover:brightness-110 disabled:opacity-50"
                        style={{
                          border: "1px solid var(--green)",
                          color: "var(--green)",
                          background: "rgba(0, 230, 138, 0.08)",
                        }}
                      >
                        {isApproving ? "Approving..." : "Approve Scene"}
                      </button>
                    )}
                  </div>

                  {/* Right: storyboard thumbnails */}
                  <div className="md:w-2/5">
                    {hasStoryboards ? (
                      <div className="grid grid-cols-3 gap-1.5">
                        {segment.storyboards.map((url, i) => (
                          <div
                            key={i}
                            className="aspect-video rounded relative overflow-hidden"
                            style={{
                              background: "var(--bg-elevated)",
                              border: "1px solid var(--border-subtle)",
                            }}
                          >
                            {url ? (
                              <img
                                src={url}
                                alt={`Storyboard ${i + 1}`}
                                className="absolute inset-0 w-full h-full object-cover"
                              />
                            ) : (
                              <div className="absolute inset-0 flex items-center justify-center">
                                <span className="text-[9px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                                  {i + 1}
                                </span>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div
                        className="h-full min-h-[80px] rounded-lg flex items-center justify-center"
                        style={{ background: "var(--bg-elevated)", border: "1px dashed var(--border-subtle)" }}
                      >
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          No storyboard
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </GlassCard>
            );
          })}
        </div>

        {/* Right sidebar */}
        <div className="space-y-4">
          <GlassCard className="p-5">
            <div className="space-y-4">
              <div>
                <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                  Total Segments
                </p>
                <p className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
                  {totalSegments}
                </p>
              </div>

              <div>
                <p className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
                  Approved
                </p>
                <div className="flex items-center gap-3">
                  <p className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
                    {approvedCount}
                  </p>
                  <ProgressRing
                    value={totalSegments > 0 ? (approvedCount / totalSegments) * 100 : 0}
                    size={50}
                    color="var(--turquoise)"
                    strokeWidth={4}
                  />
                </div>
                <p className="text-[10px] font-mono mt-1" style={{ color: "var(--text-tertiary)" }}>
                  {totalSegments > 0 ? Math.round((approvedCount / totalSegments) * 100) : 0}% complete
                </p>
              </div>

              <div className="pt-3 space-y-2" style={{ borderTop: "1px solid var(--border-subtle)" }}>
                <div>
                  <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                    Voice Status
                  </p>
                  <p className="text-sm font-mono font-medium" style={{ color: hasVoice ? "var(--green)" : "var(--text-tertiary)" }}>
                    {hasVoice ? "Voice Ready" : "Pending"}
                  </p>
                </div>
              </div>
            </div>
          </GlassCard>

          <div className="space-y-2">
            <ActionButton
              variant="filled"
              icon={approvingAll ? Loader2 : allApproved ? Check : undefined}
              className="w-full"
              onClick={handleApproveAll}
              disabled={approvingAll || allApproved}
            >
              {approvingAll ? "Approving..." : allApproved ? "All Approved" : "Approve All & Continue"}
            </ActionButton>
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
          {/* Now playing */}
          <div className="flex items-center gap-2 shrink-0 min-w-0">
            {activeSegment && (
              <span className="text-xs font-mono truncate" style={{ color: "var(--text-secondary)" }}>
                S-{String(segments.find((s) => s.id === activeSegment)?.sceneNumber || 0).padStart(2, "0")}
              </span>
            )}
          </div>

          {/* Playback controls */}
          <div className="flex items-center gap-3">
            <button onClick={playPrev} style={{ color: "var(--text-secondary)" }}>
              <SkipBack size={18} />
            </button>
            <button
              onClick={() => {
                if (activeSegment) {
                  toggleSegmentPlay(activeSegment, segments.find((s) => s.id === activeSegment)?.voiceOverUrl || null);
                } else if (segments.length > 0) {
                  toggleSegmentPlay(segments[0].id, segments[0].voiceOverUrl);
                }
              }}
              className="w-10 h-10 rounded-full flex items-center justify-center"
              style={{ background: "var(--green)" }}
            >
              {activeSegment ? (
                <Pause size={18} style={{ color: "var(--bg-void)" }} />
              ) : (
                <Play size={18} style={{ color: "var(--bg-void)" }} className="ml-0.5" />
              )}
            </button>
            <button onClick={playNext} style={{ color: "var(--text-secondary)" }}>
              <SkipForward size={18} />
            </button>

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
