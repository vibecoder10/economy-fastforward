"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getVideos, getVideo, advanceVideo, type VideoSummary, type VideoDetail } from "@/lib/api";
import { VideoCard } from "@/components/video-card";
import { DetailPanel } from "@/components/detail-panel";
import { StageTracker } from "@/components/stage-tracker";
import { FILTER_OPTIONS, getStageLabel } from "@/lib/constants";
import { formatCost, timeAgo } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { LayoutList, LayoutGrid } from "lucide-react";

export default function PipelinePage() {
  const [filter, setFilter] = useState("all");
  const [viewMode, setViewMode] = useState<"list" | "grid">("list");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: videos = [], isLoading } = useQuery({
    queryKey: ["videos", filter],
    queryFn: () => getVideos(filter === "all" ? undefined : filter),
  });

  const { data: selectedVideo } = useQuery({
    queryKey: ["video", selectedId],
    queryFn: () => getVideo(selectedId!),
    enabled: !!selectedId,
  });

  const advanceMutation = useMutation({
    mutationFn: (id: string) => advanceVideo(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      queryClient.invalidateQueries({ queryKey: ["video", selectedId] });
    },
  });

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Pipeline</h1>
        <div className="flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-0.5">
          <button
            onClick={() => setViewMode("list")}
            className={cn(
              "rounded-md p-1.5",
              viewMode === "list" ? "bg-[var(--surface-elevated)]" : "text-[var(--text-secondary)]"
            )}
          >
            <LayoutList size={16} />
          </button>
          <button
            onClick={() => setViewMode("grid")}
            className={cn(
              "rounded-md p-1.5",
              viewMode === "grid" ? "bg-[var(--surface-elevated)]" : "text-[var(--text-secondary)]"
            )}
          >
            <LayoutGrid size={16} />
          </button>
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {FILTER_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            onClick={() => setFilter(opt.key)}
            className={cn(
              "flex-shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
              filter === opt.key
                ? "bg-[var(--accent)] text-black"
                : "bg-[var(--surface)] text-[var(--text-secondary)] hover:bg-[var(--surface-elevated)]"
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Loading skeletons */}
      {isLoading && (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-xl bg-[var(--surface)]" />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && videos.length === 0 && (
        <div className="flex h-40 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface)]">
          <p className="text-sm text-[var(--text-secondary)]">
            No videos{filter !== "all" ? ` in ${getStageLabel(filter)}` : ""}
          </p>
        </div>
      )}

      {/* List view */}
      {viewMode === "list" && (
        <div className="space-y-2">
          {videos.map((video) => (
            <VideoCard key={video.id} video={video} onClick={() => setSelectedId(video.id)} />
          ))}
        </div>
      )}

      {/* Grid view */}
      {viewMode === "grid" && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
          {videos.map((video) => (
            <button
              key={video.id}
              onClick={() => setSelectedId(video.id)}
              className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] text-left transition-colors hover:bg-[var(--surface-elevated)]"
            >
              <div className="aspect-video w-full bg-[var(--surface-elevated)]">
                {video.thumbnail_url ? (
                  <img src={video.thumbnail_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  <div
                    className="flex h-full w-full items-center justify-center text-2xl font-bold text-white/10"
                    style={{ background: `${video.accent_color}15` }}
                  >
                    {(video.video_title || "?").charAt(0)}
                  </div>
                )}
              </div>
              <div className="p-2.5">
                <p className="line-clamp-2 text-xs font-medium">{video.video_title || "Untitled"}</p>
                <div className="mt-1.5 flex items-center gap-2">
                  <span className="rounded-full bg-[var(--surface-elevated)] px-1.5 py-0.5 text-[9px] font-medium text-[var(--text-secondary)]">
                    {getStageLabel(video.status)}
                  </span>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Detail panel */}
      <DetailPanel
        open={!!selectedId}
        onClose={() => setSelectedId(null)}
        title={selectedVideo?.video_title}
      >
        {selectedVideo && (
          <div className="space-y-6">
            {/* Thumbnail */}
            {selectedVideo.thumbnail_url && (
              <div className="aspect-video w-full overflow-hidden rounded-lg">
                <img src={selectedVideo.thumbnail_url} alt="" className="h-full w-full object-cover" />
              </div>
            )}

            {/* Stage tracker */}
            <div>
              <h3 className="mb-3 text-sm font-medium text-[var(--text-secondary)]">Progress</h3>
              <StageTracker status={selectedVideo.status} />
            </div>

            {/* Actions */}
            <div className="flex gap-2">
              <button
                onClick={() => advanceMutation.mutate(selectedVideo.id)}
                disabled={advanceMutation.isPending || selectedVideo.status === "done"}
                className="flex-1 rounded-lg bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-black transition-opacity disabled:opacity-50"
              >
                {advanceMutation.isPending ? "Advancing..." : "Advance Stage"}
              </button>
            </div>

            {/* Metadata */}
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Cost</span>
                <span>{formatCost(selectedVideo.total_cost)}</span>
              </div>
              {selectedVideo.views > 0 && (
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">Views</span>
                  <span>{selectedVideo.views.toLocaleString()}</span>
                </div>
              )}
              {selectedVideo.ctr !== null && (
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">CTR</span>
                  <span>{selectedVideo.ctr}%</span>
                </div>
              )}
              {selectedVideo.visual_style && (
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">Visual Style</span>
                  <span>{selectedVideo.visual_style}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-[var(--text-secondary)]">Updated</span>
                <span>{timeAgo(selectedVideo.updated_at)}</span>
              </div>
            </div>
          </div>
        )}
      </DetailPanel>
    </div>
  );
}
