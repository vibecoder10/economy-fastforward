"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Image as ImageIcon,
  Video,
  Mic,
  Loader2,
  ChevronRight,
  Film,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import {
  getVideos,
  getVideoAssets,
  getVideoScript,
  runPipelineStage,
  clearStaleTask,
  type VideoSummary,
  type Asset,
  type ScriptScene,
} from "@/lib/api";
import { getStageLabel } from "@/lib/constants";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import { timeAgo, toDisplayImageUrl } from "@/lib/utils";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const RENDER_STATUSES = new Set([
  "ready_to_render",
  "rendering",
  "rendered",
  "uploaded_draft",
  "uploaded",
]);

interface RenderCardProps {
  video: VideoSummary;
}

function RenderCard({ video }: RenderCardProps) {
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [isRendering, setIsRendering] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);
  const [thumbError, setThumbError] = useState(false);

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: taskRunning,
    interval: 10000,
    onComplete: () => {
      setTaskRunning(false);
      setIsRendering(false);
      queryClient.invalidateQueries({ queryKey: ["videos"] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setIsRendering(false);
      toast.error(`Render failed: ${error}`);
    },
  });

  const { data: assets = [] } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
    enabled: video.status === "ready_to_render",
  });

  const { data: scripts = [] } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
    enabled: video.status === "ready_to_render",
  });

  const imageCount = assets.filter((a: Asset) => a.image_url).length;
  const clipCount = assets.filter((a: Asset) => a.video_clip_url).length;
  const voiceCount = scripts.filter((s: ScriptScene) => s.voice_over_url).length;

  const handleRender = useCallback(async () => {
    setIsRendering(true);
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

  const isActive = isRendering || taskRunning || video.status === "rendering";
  const isReady = video.status === "ready_to_render";
  const isDone = video.status === "rendered" || video.status === "uploaded_draft" || video.status === "uploaded";

  const statusColor = isDone ? "green" : isActive ? "red" : isReady ? "orange" : "turquoise";

  return (
    <GlassCard className="p-5">
      <div className="flex items-start gap-4">
        {/* Thumbnail placeholder */}
        <div
          className="w-24 h-14 rounded-lg shrink-0 flex items-center justify-center overflow-hidden"
          style={{ background: "var(--bg-elevated)" }}
        >
          {video.thumbnail_url && !thumbError ? (
            <img
              src={toDisplayImageUrl(video.thumbnail_url)}
              alt={video.video_title || ""}
              className="w-full h-full object-cover"
              onError={() => setThumbError(true)}
            />
          ) : (
            <Film size={20} style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
          )}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3
              className="text-sm font-semibold truncate"
              style={{ color: "var(--text-primary)" }}
            >
              {video.video_title || "Untitled"}
            </h3>
            <StatusPill
              label={isActive ? (taskMessage || "Rendering...") : getStageLabel(video.status || "")}
              color={statusColor}
              pulse={isActive}
              size="sm"
            />
          </div>

          {/* Asset readiness */}
          {isReady && (
            <div className="flex items-center gap-4 text-[11px] font-mono mt-1">
              <span style={{ color: imageCount > 0 ? "var(--turquoise)" : "var(--text-tertiary)" }}>
                <ImageIcon size={10} className="inline mr-1" />
                {imageCount} images
              </span>
              <span style={{ color: clipCount > 0 ? "var(--purple)" : "var(--text-tertiary)" }}>
                <Video size={10} className="inline mr-1" />
                {clipCount} clips
              </span>
              <span style={{ color: voiceCount > 0 ? "var(--green)" : "var(--text-tertiary)" }}>
                <Mic size={10} className="inline mr-1" />
                {voiceCount} voices
              </span>
            </div>
          )}

          {video.updated_at && (
            <p className="text-[10px] mt-1" style={{ color: "var(--text-tertiary)" }}>
              Updated {timeAgo(video.updated_at)}
            </p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          {isReady && (
            <ActionButton
              variant="warning"
              icon={isActive ? Loader2 : undefined}
              onClick={handleRender}
              disabled={isActive}
            >
              {isActive ? "Rendering..." : "Render"}
            </ActionButton>
          )}
          <button
            onClick={() => router.push(`/pipeline/${video.id}`)}
            className="p-2 rounded-lg transition-colors hover:bg-[var(--bg-elevated)]"
          >
            <ChevronRight size={16} style={{ color: "var(--text-secondary)" }} />
          </button>
        </div>
      </div>
    </GlassCard>
  );
}

export default function RenderPage() {
  const { data: videos = [], isLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
    refetchInterval: 15000,
  });

  const renderVideos = videos.filter(
    (v: VideoSummary) => v.status && RENDER_STATUSES.has(v.status)
  );

  const readyCount = renderVideos.filter((v) => v.status === "ready_to_render").length;
  const activeCount = renderVideos.filter((v) => v.status === "rendering").length;
  const doneCount = renderVideos.filter(
    (v) => v.status === "rendered" || v.status === "uploaded_draft" || v.status === "uploaded"
  ).length;

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-4">
          <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
            Render Pipeline
          </h1>
          {activeCount > 0 && (
            <StatusPill label={`${activeCount} Rendering`} color="red" pulse size="md" />
          )}
        </div>
      </motion.div>

      {/* Stats */}
      <motion.div variants={item} className="flex gap-4">
        {[
          { label: "Ready", count: readyCount, color: "var(--orange)" },
          { label: "Rendering", count: activeCount, color: "var(--red)" },
          { label: "Complete", count: doneCount, color: "var(--green)" },
        ].map(({ label, count, color }) => (
          <GlassCard key={label} className="px-4 py-3 flex-1">
            <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
              {label}
            </p>
            <p className="text-2xl font-mono font-bold mt-1" style={{ color }}>
              {count}
            </p>
          </GlassCard>
        ))}
      </motion.div>

      {/* Video list */}
      {renderVideos.length === 0 ? (
        <motion.div variants={item}>
          <GlassCard className="p-12 text-center">
            <Film size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
            <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
              No Videos in Render Stage
            </p>
            <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
              Videos will appear here once they reach the render stage of the pipeline.
            </p>
          </GlassCard>
        </motion.div>
      ) : (
        <motion.div variants={container} className="space-y-3">
          {renderVideos.map((video) => (
            <motion.div key={video.id} variants={item}>
              <RenderCard video={video} />
            </motion.div>
          ))}
        </motion.div>
      )}
    </motion.div>
  );
}
