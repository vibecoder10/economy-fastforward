"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Loader2,
  Image as ImageIcon,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import {
  getVideos,
  getVideoAssets,
  getVideo,
  runPipelineStage,
  clearStaleTask,
  type VideoSummary,
  type Asset,
} from "@/lib/api";
import { getStageLabel } from "@/lib/constants";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import { formatCost } from "@/lib/utils";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.06 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const IMAGE_STATUSES = new Set([
  "ready_for_image_prompts",
  "ready_for_images",
  "ready_for_storyboard_images",
]);

const COST_PER_IMAGE = 0.025;

interface VideoImageSectionProps {
  video: VideoSummary;
}

function VideoImageSection({ video }: VideoImageSectionProps) {
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [isGenerating, setIsGenerating] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: taskRunning,
    interval: 3000,
    onComplete: () => {
      setTaskRunning(false);
      setIsGenerating(false);
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setIsGenerating(false);
      toast.error(`Image generation failed: ${error}`);
    },
  });

  const { data: assets = [] } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });

  const { data: detail } = useQuery({
    queryKey: ["video", video.id],
    queryFn: () => getVideo(video.id),
  });

  const imageAssets = assets.filter((a: Asset) => a.image_prompt || a.image_url);
  const completedCount = imageAssets.filter((a: Asset) => a.image_url).length;
  const totalCount = imageAssets.length;
  const progressPct = totalCount > 0 ? (completedCount / totalCount) * 100 : 0;
  const estimatedCost = totalCount * COST_PER_IMAGE;

  const handleGenerate = useCallback(async () => {
    setIsGenerating(true);
    const stage = video.status === "ready_for_image_prompts" ? "prompts" : "images";
    try {
      await runPipelineStage(video.id, stage);
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, stage);
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          toast.error(`Generation failed: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`Generation failed: ${message}`);
      }
      setIsGenerating(false);
    }
  }, [video.id, video.status]);

  const isActive = isGenerating || taskRunning;

  return (
    <motion.div variants={item}>
      {/* Video header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3 min-w-0">
          <h3 className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }}>
            {video.video_title || "Untitled"}
          </h3>
          <StatusPill
            label={isActive ? (taskMessage || "Generating...") : getStageLabel(video.status || "")}
            color={isActive ? "purple" : "turquoise"}
            pulse={isActive}
            size="sm"
          />
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <ActionButton
            variant="outline"
            icon={isActive ? Loader2 : Sparkles}
            onClick={handleGenerate}
            disabled={isActive}
          >
            {isActive ? "Generating..." : video.status === "ready_for_image_prompts" ? "Generate Prompts" : "Generate Images"}
          </ActionButton>
          <button
            onClick={() => router.push(`/pipeline/${video.id}`)}
            className="p-2 rounded-lg transition-colors hover:bg-[var(--bg-elevated)]"
          >
            <ChevronRight size={16} style={{ color: "var(--text-secondary)" }} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_220px] gap-4">
        {/* Image grid */}
        {totalCount > 0 ? (
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
            {imageAssets.map((asset: Asset) => (
              <GlassCard key={asset.id} className="p-0 overflow-hidden">
                <div
                  className="aspect-square relative flex items-center justify-center"
                  style={{ background: "var(--bg-elevated)" }}
                >
                  {asset.image_url ? (
                    <img
                      src={asset.image_url}
                      alt={asset.sentence_text || asset.image_prompt || ""}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <>
                      <svg className="absolute inset-0 w-full h-full opacity-15">
                        <defs>
                          <pattern id={`vg-${asset.id}`} width="20" height="20" patternUnits="userSpaceOnUse">
                            <path d="M 20 0 L 0 0 0 20" fill="none" stroke="var(--purple)" strokeWidth="0.5" />
                          </pattern>
                        </defs>
                        <rect width="100%" height="100%" fill={`url(#vg-${asset.id})`} />
                      </svg>
                      <ImageIcon size={20} style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
                    </>
                  )}

                  {asset.image_url && (
                    <div className="absolute top-2 right-2">
                      <div
                        className="w-5 h-5 rounded-full flex items-center justify-center"
                        style={{ background: "var(--green)" }}
                      >
                        <Check size={12} style={{ color: "var(--bg-void)" }} />
                      </div>
                    </div>
                  )}

                  {!asset.image_url && asset.status === "generating" && (
                    <div className="absolute top-2 right-2">
                      <Loader2 size={16} className="animate-spin" style={{ color: "var(--purple)" }} />
                    </div>
                  )}

                  <div className="absolute bottom-2 right-2">
                    <SegmentBadge
                      label={`S-${String(asset.scene ?? 0).padStart(2, "0")}.${asset.image_index ?? 0}`}
                      color="var(--purple)"
                    />
                  </div>
                </div>

                <div className="px-3 py-2">
                  <p className="text-[11px] font-mono truncate" style={{ color: "var(--text-secondary)" }}>
                    <ImageIcon size={10} className="inline mr-1" style={{ color: "var(--purple)" }} />
                    {asset.image_prompt || asset.sentence_text || "No prompt"}
                  </p>
                </div>

                {/* Progress bar */}
                <div className="h-1" style={{ background: "var(--bg-void)" }}>
                  <div
                    className="h-full"
                    style={{
                      background: "var(--purple)",
                      width: asset.image_url ? "100%" : "0%",
                    }}
                  />
                </div>
              </GlassCard>
            ))}
          </div>
        ) : (
          <GlassCard className="p-8 text-center">
            <ImageIcon size={24} className="mx-auto mb-2" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              No image assets yet. Generate prompts first.
            </p>
          </GlassCard>
        )}

        {/* Stats sidebar */}
        <div className="space-y-4">
          <GlassCard className="p-5">
            <h4 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>
              Generation Stats
            </h4>
            <div className="flex justify-center mb-3">
              <ProgressRing value={progressPct} size={80} color="var(--purple)" strokeWidth={6}>
                <span className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>{completedCount}</span>
                <span className="text-[8px] uppercase" style={{ color: "var(--text-secondary)" }}>/ {totalCount}</span>
              </ProgressRing>
            </div>
            {detail?.visual_style && (
              <p className="text-[10px] text-center mb-2" style={{ color: "var(--text-tertiary)" }}>
                Style: {detail.visual_style.replace(/_/g, " ")}
              </p>
            )}
            <div className="pt-3" style={{ borderTop: "1px solid var(--border-subtle)" }}>
              <p className="text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>
                Estimated Cost
              </p>
              <p className="text-lg font-mono" style={{ color: "var(--gold)" }}>
                {formatCost(estimatedCost)}
              </p>
            </div>
          </GlassCard>
        </div>
      </div>
    </motion.div>
  );
}

export default function VisualsPage() {
  const { data: videos = [], isLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
    refetchInterval: 15000,
  });

  const imageVideos = videos.filter(
    (v: VideoSummary) => v.status && IMAGE_STATUSES.has(v.status)
  );

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
      <motion.div variants={item} className="flex items-center gap-4 flex-wrap">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Visual Generation
        </h1>
        {imageVideos.length > 0 && (
          <StatusPill
            label={`${imageVideos.length} Active`}
            color="purple"
            pulse
            size="md"
          />
        )}
      </motion.div>

      {/* Videos with image generation */}
      {imageVideos.length === 0 ? (
        <motion.div variants={item}>
          <GlassCard className="p-12 text-center">
            <ImageIcon size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
            <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
              No Active Image Generation
            </p>
            <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
              Videos in the image generation stage will appear here with their real-time progress.
            </p>
          </GlassCard>
        </motion.div>
      ) : (
        <div className="space-y-8">
          {imageVideos.map((video) => (
            <VideoImageSection key={video.id} video={video} />
          ))}
        </div>
      )}
    </motion.div>
  );
}
