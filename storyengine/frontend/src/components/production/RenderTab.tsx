"use client";

import { useState, useCallback } from "react";
import { Image as ImageIcon, Video, Mic, Volume2, Loader2, Play, Download, CheckCircle2, ChevronRight, ExternalLink } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { ActionButton } from "@/components/ui/ActionButton";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { getVideoAssets, getVideoScript, runPipelineStage, clearStaleTask, advanceVideo } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import type { VideoDetail, Asset } from "@/lib/api";

interface RenderTabProps {
  video: VideoDetail & {
    id: string;
    status?: string;
    videoLengthMin?: number | null;
  };
  onAdvanced?: () => void;
}

function formatDuration(minutes: number | null | undefined): string {
  if (!minutes) return "0:00";
  const mins = Math.floor(minutes);
  const secs = Math.round((minutes - mins) * 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

/** Convert Google Drive share URLs to direct-playable format */
function toDrivePlayableUrl(url: string): string {
  const match = url.match(/drive\.google\.com\/file\/d\/([^/]+)/);
  if (match) return `https://drive.google.com/uc?export=download&id=${match[1]}`;
  return url;
}

interface TimelineSegment {
  sceneNumber: number;
  hasImage: boolean;
  hasClip: boolean;
  hasVoice: boolean;
  duration: string;
}

export function RenderTab({ video, onAdvanced }: RenderTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [isRendering, setIsRendering] = useState(false);
  const [confirmRender, setConfirmRender] = useState(false);
  const [musicTrack, setMusicTrack] = useState("tension");
  const [exportFormat, setExportFormat] = useState("mp4");
  const [taskRunning, setTaskRunning] = useState(false);
  const [videoError, setVideoError] = useState(false);

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: taskRunning,
    interval: 10000,
    onComplete: () => {
      setTaskRunning(false);
      setIsRendering(false);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setIsRendering(false);
      toast.error(`Render failed: ${error}`);
    },
  });

  const isRenderStatus = video.status === "rendering";

  const { data: assets = [] } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });

  const { data: scriptScenes = [] } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });

  // Build scene timeline
  const timeline: TimelineSegment[] = scriptScenes.map((scene) => {
    const sceneAssets = assets.filter((a) => a.scene === scene.scene);
    const wordCount = (scene.scene_text || "").split(/\s+/).length;
    return {
      sceneNumber: scene.scene || 0,
      hasImage: sceneAssets.some((a) => a.image_url),
      hasClip: sceneAssets.some((a) => a.video_clip_url),
      hasVoice: !!scene.voice_over_url,
      duration: `${Math.round(wordCount / 2.5)}s`,
    };
  });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const vid = video as any;
  const duration = formatDuration(video.video_length_minutes ?? vid.videoLengthMin);

  const handleRender = useCallback(async () => {
    setIsRendering(true);
    setConfirmRender(false);
    try {
      await runPipelineStage(video.id, "render");
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "render");
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          toast.error(`Render failed: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`Render failed: ${message}`);
      }
      setIsRendering(false);
    }
  }, [video.id]);

  const renderActive = isRendering || isRenderStatus || taskRunning;

  const [advancing, setAdvancing] = useState(false);
  const handleAdvanceStage = useCallback(async () => {
    setAdvancing(true);
    try {
      await advanceVideo(video.id);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      onAdvanced?.();
    } catch (err) {
      toast.error(`Failed to advance: ${(err as Error).message}`);
    } finally {
      setAdvancing(false);
    }
  }, [video.id, queryClient, onAdvanced]);

  return (
    <>
    {/* Top action bar */}
    <div className="rounded-xl px-4 py-3 mb-4" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-4 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
          <span>Render: <span style={{ color: renderActive ? "var(--gold)" : video.final_video_url ? "var(--green)" : "var(--text-tertiary)" }}>{renderActive ? "In Progress" : video.final_video_url ? "Complete" : "Pending"}</span></span>
          <span>Video: <span style={{ color: video.final_video_url ? "var(--green)" : "var(--text-tertiary)" }}>{video.final_video_url ? "Ready" : "Not Ready"}</span></span>
        </div>
        <button onClick={handleAdvanceStage} disabled={advancing}
          className="px-3 py-1.5 rounded-lg text-[10px] font-semibold inline-flex items-center gap-1 disabled:opacity-50 transition-all hover:brightness-110"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
          {advancing ? <Loader2 size={12} className="animate-spin" /> : null}
          Advance Stage <ChevronRight size={12} />
        </button>
      </div>
    </div>

    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      <div className="space-y-4">
        {/* Video preview */}
        <GlassCard className="p-0 overflow-hidden">
          <div
            className="aspect-video relative flex items-center justify-center"
            style={{ background: "var(--bg-elevated)" }}
          >
            {video.final_video_url && !renderActive && !videoError ? (
              <video
                src={toDrivePlayableUrl(video.final_video_url)}
                poster={video.thumbnail_url || undefined}
                controls
                className="absolute inset-0 w-full h-full object-contain"
                style={{ background: "black" }}
                onError={() => setVideoError(true)}
              />
            ) : video.final_video_url && !renderActive && videoError ? (
              <div className="flex flex-col items-center gap-3">
                <Video size={32} style={{ color: "var(--text-tertiary)" }} />
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  Video available on Google Drive
                </p>
                <a
                  href={video.final_video_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg"
                  style={{ color: "var(--turquoise)", background: "rgba(0,212,170,0.1)", border: "1px solid rgba(0,212,170,0.25)" }}
                >
                  <ExternalLink size={13} />
                  Open in Drive
                </a>
              </div>
            ) : video.youtube_url && !renderActive ? (
              <div className="absolute inset-0 flex items-center justify-center">
                <button
                  className="w-16 h-16 rounded-full flex items-center justify-center transition-transform hover:scale-110"
                  style={{ background: "rgba(0, 212, 170, 0.2)" }}
                  onClick={() => {
                    if (video.youtube_url) window.open(video.youtube_url, "_blank");
                  }}
                >
                  <Play size={28} style={{ color: "var(--turquoise)" }} className="ml-1" />
                </button>
              </div>
            ) : renderActive ? (
              <div className="absolute inset-0 flex items-center justify-center">
                <ProgressRing value={0} size={120} color="var(--red)" strokeWidth={6}>
                  <Loader2 size={24} className="animate-spin" style={{ color: "var(--red)" }} />
                </ProgressRing>
              </div>
            ) : (
              <svg width="80" height="60" viewBox="0 0 80 60" className="opacity-20">
                <rect x="5" y="8" width="50" height="40" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" />
                <line x1="5" y1="8" x2="15" y2="2" stroke="var(--text-tertiary)" strokeWidth="1.5" />
                <line x1="55" y1="8" x2="65" y2="2" stroke="var(--text-tertiary)" strokeWidth="1.5" />
                <rect x="15" y="2" width="50" height="40" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" />
              </svg>
            )}
          </div>
        </GlassCard>

        {/* Video metadata bar */}
        {video.final_video_url && !renderActive && (
          <div
            className="flex items-center justify-between px-4 py-2.5 rounded-lg"
            style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
          >
            <div className="flex items-center gap-3 text-xs font-mono">
              <span style={{ color: "var(--text-secondary)" }}>
                Duration: <span style={{ color: "var(--text-primary)" }}>{duration}</span>
              </span>
              <span
                className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider"
                style={{
                  background: video.status === "uploaded_draft" || video.status === "uploaded" || video.status === "done"
                    ? "rgba(96,165,250,0.15)" : "rgba(0,230,138,0.15)",
                  color: video.status === "uploaded_draft" || video.status === "uploaded" || video.status === "done"
                    ? "#60A5FA" : "var(--green)",
                }}
              >
                {video.status === "uploaded_draft" || video.status === "uploaded" || video.status === "done" ? "Uploaded" : "Rendered"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {vid.drive_folder_link && (
                <a
                  href={vid.drive_folder_link as string}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded-lg transition-opacity hover:opacity-80"
                  style={{ color: "var(--text-secondary)", border: "1px solid var(--border)" }}
                >
                  <ExternalLink size={11} /> Drive
                </a>
              )}
              <a
                href={video.final_video_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded-lg transition-opacity hover:opacity-80"
                style={{ color: "var(--turquoise)", border: "1px solid rgba(0,212,170,0.25)" }}
              >
                <Download size={11} /> Download
              </a>
            </div>
          </div>
        )}

        {/* Render output */}
        {video.final_video_url && !renderActive && (
          <GlassCard className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CheckCircle2 size={16} style={{ color: "var(--green)" }} />
                <span className="text-xs font-semibold" style={{ color: "var(--green)" }}>
                  Render Complete
                </span>
              </div>
              <a
                href={video.final_video_url}
                download
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg transition-opacity hover:opacity-80"
                style={{
                  color: "var(--turquoise)",
                  background: "rgba(0, 212, 170, 0.1)",
                  border: "1px solid rgba(0, 212, 170, 0.25)",
                }}
              >
                <Download size={13} />
                Download MP4
              </a>
            </div>
          </GlassCard>
        )}

        {/* Scene timeline */}
        <GlassCard className="p-4">
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-3"
            style={{ color: "var(--text-secondary)" }}
          >
            Scene Timeline
          </h3>
          {timeline.length > 0 ? (
            <div className="flex items-stretch gap-1 overflow-x-auto pb-1">
              {timeline.map((seg) => {
                // Color based on readiness
                const color = seg.hasVoice && seg.hasImage
                  ? "var(--green)"
                  : seg.hasImage
                    ? "var(--turquoise)"
                    : "var(--text-tertiary)";

                return (
                  <div
                    key={seg.sceneNumber}
                    className="flex-1 min-w-[40px] rounded-lg px-1.5 py-2 text-center"
                    style={{
                      background: `color-mix(in srgb, ${color} 12%, transparent)`,
                      border: `1px solid color-mix(in srgb, ${color} 25%, transparent)`,
                    }}
                  >
                    <span className="text-[9px] font-mono block" style={{ color }}>
                      S{seg.sceneNumber}
                    </span>
                    <span className="text-[8px] font-mono block mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                      {seg.duration}
                    </span>
                    <div className="flex items-center justify-center gap-0.5 mt-1">
                      {seg.hasImage && <ImageIcon size={7} style={{ color: "var(--turquoise)" }} />}
                      {seg.hasClip && <Video size={7} style={{ color: "var(--purple)" }} />}
                      {seg.hasVoice && <Mic size={7} style={{ color: "var(--green)" }} />}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-xs italic" style={{ color: "var(--text-tertiary)" }}>
              No scenes yet. Generate scripts and assets to build the timeline.
            </p>
          )}
        </GlassCard>

        {/* Render status info */}
        {renderActive && (
          <GlassCard className="p-4">
            <div className="flex items-center gap-6 text-xs font-mono flex-wrap">
              <span>
                Status:{" "}
                <span style={{ color: "var(--turquoise)" }}>{taskMessage || "Rendering..."}</span>
              </span>
              <span>
                Resolution:{" "}
                <span style={{ color: "var(--turquoise)" }}>1920x1080</span>
              </span>
              <span>
                FPS: <span style={{ color: "var(--gold)" }}>30</span>
              </span>
            </div>
          </GlassCard>
        )}
      </div>

      {/* Sidebar */}
      <div className="space-y-4">
        <GlassCard className="p-5">
          <div className="space-y-3">
            {[
              { label: "Resolution", value: "1920x1080" },
              { label: "FPS", value: "30" },
              { label: "Duration", value: duration },
              { label: "Scenes", value: String(scriptScenes.length) },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  {row.label}
                </span>
                <span
                  className="text-sm font-mono font-medium"
                  style={{ color: "var(--text-primary)" }}
                >
                  {row.value}
                </span>
              </div>
            ))}
          </div>
          <div className="mt-4 space-y-3">
            <FilterSelect
              label="Music Track"
              options={[
                { value: "tension", label: "Tension Rising" },
                { value: "ambient", label: "Dark Ambient" },
                { value: "none", label: "No Music" },
              ]}
              value={musicTrack}
              onChange={setMusicTrack}
              disabled
              title="Render music selection is not wired to the production backend yet."
            />
            <FilterSelect
              label="Export Format"
              options={[
                { value: "mp4", label: "MP4 (H.264)" },
                { value: "webm", label: "WebM (VP9)" },
              ]}
              value={exportFormat}
              onChange={setExportFormat}
              disabled
              title="Render export format selection is not wired to the production backend yet."
            />
            <p className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
              Render overrides will be enabled once backend render options are wired end to end.
            </p>
          </div>
        </GlassCard>

        <div className="space-y-2">
          {confirmRender ? (
            <>
              <p className="text-[11px] text-center mb-2" style={{ color: "var(--text-secondary)" }}>
                This will start rendering the video. Continue?
              </p>
              <ActionButton
                variant="warning"
                icon={isRendering ? Loader2 : undefined}
                className="w-full"
                onClick={handleRender}
                disabled={renderActive}
              >
                {renderActive ? "Rendering..." : "Confirm Render"}
              </ActionButton>
              <ActionButton
                variant="outline"
                className="w-full"
                onClick={() => setConfirmRender(false)}
              >
                Cancel
              </ActionButton>
            </>
          ) : (
            <ActionButton
              variant="warning"
              className="w-full"
              onClick={() => setConfirmRender(true)}
              disabled={renderActive}
            >
              {renderActive ? "Rendering..." : "Render Now"}
            </ActionButton>
          )}
        </div>
      </div>
    </div>
    </>
  );
}
