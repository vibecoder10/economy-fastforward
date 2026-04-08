"use client";

import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronRight, Layers, Loader2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import {
  getVideos,
  getVideoScript,
  advanceVideo,
  type VideoSummary,
  type ScriptScene,
} from "@/lib/api";
import { getStageLabel } from "@/lib/constants";
import { useToast } from "@/components/ui/toast";
import { timeAgo } from "@/lib/utils";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const STORYBOARD_STATUSES = new Set([
  "ready_for_storyboards",
  "ready_for_storyboard_images",
  "ready_for_storyboard_extraction",
]);

interface StoryboardVideoCardProps {
  video: VideoSummary;
}

function StoryboardVideoCard({ video }: StoryboardVideoCardProps) {
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();

  const { data: scripts = [] } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });

  const approveMutation = useMutation({
    mutationFn: () => advanceVideo(video.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["videos"] });
    },
    onError: (err) => {
      toast.error(`Advance failed: ${(err as Error).message}`);
    },
  });

  // Scenes that have storyboard grids
  const scenesWithBoards = scripts.filter(
    (s: ScriptScene) =>
      s.storyboard_1_url || s.storyboard_2_url || s.storyboard_3_url
  );
  const totalScenes = scripts.filter((s: ScriptScene) => s.scene !== null).length;

  // Get first storyboard grid URL for thumbnail preview
  const previewUrl =
    scenesWithBoards[0]?.storyboard_1_url ||
    scenesWithBoards[0]?.storyboard_2_url ||
    null;

  return (
    <GlassCard className="p-5">
      <div className="flex items-start gap-4 flex-col md:flex-row">
        {/* Storyboard preview */}
        <div
          className="w-full md:w-40 h-28 rounded-lg shrink-0 flex items-center justify-center overflow-hidden"
          style={{ background: "var(--bg-elevated)" }}
        >
          {previewUrl ? (
            <img
              src={previewUrl}
              alt={`Storyboard for ${video.video_title}`}
              className="w-full h-full object-cover"
            />
          ) : (
            <Layers size={24} style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
          )}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            <h3
              className="text-sm font-semibold truncate"
              style={{ color: "var(--text-primary)" }}
            >
              {video.video_title || "Untitled"}
            </h3>
            <StatusPill
              label={getStageLabel(video.status || "")}
              color="turquoise"
              size="sm"
            />
          </div>

          {/* Scene summary */}
          <div className="flex items-center gap-4 text-[11px] font-mono mt-1">
            <span style={{ color: "var(--turquoise)" }}>
              {scenesWithBoards.length}/{totalScenes} scenes with grids
            </span>
          </div>

          {/* Grid thumbnails */}
          {scenesWithBoards.length > 0 && (
            <div className="flex gap-1.5 mt-3 overflow-x-auto">
              {scenesWithBoards.slice(0, 6).map((scene: ScriptScene) => (
                <div
                  key={scene.id}
                  className="w-16 h-10 rounded shrink-0 overflow-hidden"
                  style={{
                    border: "1px solid var(--border-subtle)",
                  }}
                >
                  {scene.storyboard_1_url ? (
                    <img
                      src={scene.storyboard_1_url}
                      alt={`Scene ${scene.scene}`}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div
                      className="w-full h-full flex items-center justify-center"
                      style={{ background: "var(--bg-elevated)" }}
                    >
                      <Layers size={8} style={{ color: "var(--text-tertiary)" }} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {video.updated_at && (
            <p className="text-[10px] mt-2" style={{ color: "var(--text-tertiary)" }}>
              Updated {timeAgo(video.updated_at)}
            </p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          <ActionButton
            variant="outline"
            onClick={() => router.push(`/pipeline/${video.id}/storyboards`)}
          >
            Review
            <ChevronRight size={14} className="ml-1" />
          </ActionButton>
          <ActionButton
            variant="filled"
            icon={approveMutation.isPending ? Loader2 : Check}
            onClick={() => approveMutation.mutate()}
            disabled={approveMutation.isPending}
          >
            Advance
          </ActionButton>
        </div>
      </div>
    </GlassCard>
  );
}

export default function StoryboardReviewPage() {
  const { data: videos = [], isLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
    refetchInterval: 15000,
  });

  const storyboardVideos = videos.filter(
    (v: VideoSummary) => v.status && STORYBOARD_STATUSES.has(v.status)
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
          Storyboard Review
        </h1>
        {storyboardVideos.length > 0 && (
          <StatusPill
            label={`${storyboardVideos.length} Pending`}
            color="turquoise"
            pulse
            size="md"
          />
        )}
      </motion.div>

      {/* Video list */}
      {storyboardVideos.length === 0 ? (
        <motion.div variants={item}>
          <GlassCard className="p-12 text-center">
            <Layers size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
            <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
              No Storyboards Pending Review
            </p>
            <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
              Videos with storyboard grids awaiting review will appear here.
            </p>
          </GlassCard>
        </motion.div>
      ) : (
        <motion.div variants={container} className="space-y-4">
          {storyboardVideos.map((video) => (
            <motion.div key={video.id} variants={item}>
              <StoryboardVideoCard video={video} />
            </motion.div>
          ))}
        </motion.div>
      )}
    </motion.div>
  );
}
