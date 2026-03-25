"use client";

import { useState } from "react";
import { Image as ImageIcon, Video, Mic, Volume2, Loader2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { ActionButton } from "@/components/ui/ActionButton";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { getVideoAssets, runPipelineStage } from "@/lib/api";
import type { Video as VideoType } from "@/lib/types";
import type { Asset } from "@/lib/api";

interface RenderTabProps {
  video: VideoType & {
    video_length_minutes?: number | null;
  };
}

const BLOCK_ICONS: Record<string, React.ElementType> = {
  image: ImageIcon,
  video: Video,
  voice: Mic,
  sound: Volume2,
};

function formatDuration(minutes: number | null | undefined): string {
  if (!minutes) return "0:00";
  const mins = Math.floor(minutes);
  const secs = Math.round((minutes - mins) * 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

interface TimelineBlock {
  type: "image" | "video" | "voice" | "sound";
  label: string;
  color: string;
}

function buildTimeline(assets: Asset[]): TimelineBlock[] {
  if (assets.length === 0) return [];

  const blocks: TimelineBlock[] = [];
  // Group assets by scene, then create timeline blocks per scene
  const sorted = [...assets].sort((a, b) => (a.scene || 0) - (b.scene || 0));

  for (const asset of sorted) {
    // Each asset contributes image block
    if (asset.image_url) {
      blocks.push({ type: "image", label: "", color: "var(--turquoise)" });
    }
    // If it has a video clip, add a video block
    if (asset.video_clip_url) {
      blocks.push({ type: "video", label: "Clip", color: "var(--red)" });
    }
  }

  // Add voice blocks (one per unique scene)
  const scenes = new Set(sorted.map((a) => a.scene).filter(Boolean));
  for (const _s of scenes) {
    blocks.push({ type: "voice", label: "Voice", color: "var(--green)" });
  }

  return blocks;
}

export function RenderTab({ video }: RenderTabProps) {
  const [isRendering, setIsRendering] = useState(false);
  const isRenderStatus = video.status === "rendering";

  const { data: assets = [] } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });

  const timeline = buildTimeline(assets);
  const duration = formatDuration(video.video_length_minutes ?? video.videoLengthMin);

  const handleRender = async () => {
    setIsRendering(true);
    try {
      await runPipelineStage(video.id, "render");
    } finally {
      setIsRendering(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      <div className="space-y-4">
        {/* Video preview */}
        <GlassCard className="p-0 overflow-hidden">
          <div
            className="aspect-video relative flex items-center justify-center"
            style={{ background: "var(--bg-elevated)" }}
          >
            <svg width="80" height="60" viewBox="0 0 80 60" className="opacity-20">
              <rect x="5" y="8" width="50" height="40" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" />
              <line x1="5" y1="8" x2="15" y2="2" stroke="var(--text-tertiary)" strokeWidth="1.5" />
              <line x1="55" y1="8" x2="65" y2="2" stroke="var(--text-tertiary)" strokeWidth="1.5" />
              <rect x="15" y="2" width="50" height="40" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" />
            </svg>
            {(isRenderStatus || isRendering) && (
              <div className="absolute inset-0 flex items-center justify-center">
                <ProgressRing value={0} size={120} color="var(--red)" strokeWidth={6}>
                  <Loader2 size={24} className="animate-spin" style={{ color: "var(--red)" }} />
                </ProgressRing>
              </div>
            )}
          </div>
        </GlassCard>

        {/* Scene Composition Timeline */}
        <GlassCard className="p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>
            Scene Composition Timeline
          </h3>
          {timeline.length > 0 ? (
            <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
              {timeline.map((block, i) => {
                const Icon = BLOCK_ICONS[block.type] || ImageIcon;
                return (
                  <div
                    key={i}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg shrink-0"
                    style={{
                      background: `color-mix(in srgb, ${block.color} 15%, transparent)`,
                      border: `1px solid color-mix(in srgb, ${block.color} 25%, transparent)`,
                    }}
                  >
                    <Icon size={12} style={{ color: block.color }} />
                    {block.label && (
                      <span className="text-[11px] font-medium" style={{ color: block.color }}>{block.label}</span>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-xs italic" style={{ color: "var(--text-tertiary)" }}>
              No assets yet. Generate images and clips to build the timeline.
            </p>
          )}
        </GlassCard>

        {/* System resources (shown only during render) */}
        {(isRenderStatus || isRendering) && (
          <GlassCard className="p-4">
            <div className="flex items-center gap-6 text-xs font-mono flex-wrap">
              <span>Status: <span style={{ color: "var(--turquoise)" }}>Rendering...</span></span>
              <span>Resolution: <span style={{ color: "var(--turquoise)" }}>1920x1080</span></span>
              <span>FPS: <span style={{ color: "var(--gold)" }}>30</span></span>
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
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{row.label}</span>
                <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>{row.value}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 space-y-3">
            <FilterSelect label="Music Track" options={[{ value: "tension", label: "Tension Rising - Cinematic" }, { value: "ambient", label: "Dark Ambient" }]} value="tension" onChange={() => {}} />
            <FilterSelect label="Export Format" options={[{ value: "mp4", label: "MP4 (H.264)" }, { value: "webm", label: "WebM (VP9)" }]} value="mp4" onChange={() => {}} />
          </div>
        </GlassCard>

        <div className="space-y-2">
          <ActionButton
            variant="warning"
            icon={isRendering ? Loader2 : undefined}
            className="w-full"
            onClick={handleRender}
            disabled={isRendering || isRenderStatus}
          >
            {isRendering || isRenderStatus ? "Rendering..." : "Render Now"}
          </ActionButton>
          <ActionButton variant="filled" className="w-full">Preview Draft</ActionButton>
          <button
            className="w-full py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110"
            style={{ background: "transparent", color: "var(--gold)", border: "1px solid var(--gold)" }}
          >
            Upload to YouTube
          </button>
        </div>
      </div>
    </div>
  );
}
