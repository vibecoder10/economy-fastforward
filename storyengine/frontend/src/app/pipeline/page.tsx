"use client";

import { useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { Search, Film, Loader2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getVideos } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.05 } },
};

const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: "easeOut" as const } },
};

const COMPLETED_STATUSES = new Set(["uploaded", "uploaded_draft", "done", "published"]);

const STATUS_LABEL: Record<string, string> = {
  idea_logged: "Idea",
  approved: "Approved",
  researching: "Researching",
  ready_for_scripting: "Ready for Script",
  scripting: "Scripting",
  ready_for_voice: "Ready for Voice",
  voice: "Voice",
  ready_for_image_prompts: "Image Prompts",
  ready_for_images: "Ready for Images",
  ready_for_storyboards: "Storyboards",
  ready_for_storyboard_images: "Storyboard Images",
  ready_for_storyboard_extraction: "Storyboard Extract",
  ready_for_sound_design: "Sound Design",
  ready_for_sound_effects: "Sound Effects",
  ready_for_video_scripts: "Video Scripts",
  ready_for_video_generation: "Video Gen",
  ready_for_thumbnail: "Thumbnail",
  ready_to_render: "Ready to Render",
  rendering: "Rendering",
  rendered: "Rendered",
  uploaded: "Uploaded",
  uploaded_draft: "Draft",
  published: "Published",
  done: "Published",
};

const STATUS_COLOR: Record<string, string> = {
  idea_logged: "turquoise",
  approved: "turquoise",
  researching: "turquoise",
  ready_for_scripting: "orange",
  scripting: "orange",
  ready_for_voice: "green",
  voice: "green",
  ready_for_image_prompts: "purple",
  ready_for_images: "purple",
  ready_for_storyboards: "turquoise",
  ready_for_storyboard_images: "turquoise",
  ready_for_storyboard_extraction: "turquoise",
  ready_for_sound_design: "gold",
  ready_for_sound_effects: "gold",
  ready_for_video_scripts: "purple",
  ready_for_video_generation: "purple",
  ready_for_thumbnail: "orange",
  ready_to_render: "red",
  rendering: "red",
  rendered: "green",
  uploaded: "green",
  uploaded_draft: "gold",
  published: "green",
  done: "green",
};

// Estimate progress from status
function statusToProgress(status: string): number {
  const ORDER = [
    "idea_logged", "approved", "researching", "ready_for_scripting", "scripting",
    "ready_for_voice", "voice", "ready_for_image_prompts", "ready_for_images",
    "ready_for_storyboards", "ready_for_storyboard_images", "ready_for_storyboard_extraction",
    "ready_for_sound_design", "ready_for_sound_effects", "ready_for_video_scripts",
    "ready_for_video_generation", "ready_for_thumbnail", "ready_to_render",
    "rendering", "rendered", "uploaded", "uploaded_draft", "done",
  ];
  const idx = ORDER.indexOf(status);
  if (idx < 0) return 0;
  return Math.round((idx / (ORDER.length - 1)) * 100);
}

export default function QueuePage() {
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<"active" | "published">("active");

  const { data: videos, isLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  const allVideos = (videos || []).filter((v: any) =>
    (v.video_title || "").toLowerCase().includes(search.toLowerCase())
  );

  const activeVideos = allVideos.filter((v: any) => !COMPLETED_STATUSES.has(v.status));
  const publishedVideos = allVideos.filter((v: any) => COMPLETED_STATUSES.has(v.status));

  const displayVideos = tab === "active" ? activeVideos : publishedVideos;

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between gap-4 flex-wrap">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Queue
        </h1>
        <div className="relative max-w-xs flex-1">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2"
            style={{ color: "var(--text-tertiary)" }}
          />
          <input
            type="text"
            placeholder="Search videos..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 rounded-lg text-sm font-body outline-none transition-all"
            style={{
              background: "var(--bg-elevated)",
              color: "var(--text-primary)",
              border: "1px solid var(--border)",
            }}
            onFocus={(e) => (e.target.style.borderColor = "var(--turquoise)")}
            onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
          />
        </div>
      </motion.div>

      {/* Tabs: Active / Published */}
      <motion.div variants={item} className="flex gap-1" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
        {([
          { id: "active" as const, label: "In Production", count: activeVideos.length },
          { id: "published" as const, label: "Published", count: publishedVideos.length },
        ]).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium font-body transition-all rounded-t-lg"
            style={{
              color: tab === t.id ? "var(--turquoise)" : "var(--text-tertiary)",
              background: tab === t.id ? "var(--turquoise-bg)" : "transparent",
              borderBottom: tab === t.id ? "2px solid var(--turquoise)" : "2px solid transparent",
            }}
          >
            {t.label}
            <span
              className="text-[10px] font-mono px-1.5 py-0.5 rounded-full"
              style={{
                background: tab === t.id ? "var(--turquoise-dim)" : "rgba(255,255,255,0.05)",
                color: tab === t.id ? "var(--turquoise)" : "var(--text-tertiary)",
              }}
            >
              {t.count}
            </span>
          </button>
        ))}
      </motion.div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={24} className="animate-spin" style={{ color: "var(--turquoise)" }} />
        </div>
      )}

      {/* Empty state */}
      {!isLoading && displayVideos.length === 0 && (
        <GlassCard className="p-12 text-center">
          <Film size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {search ? "No videos match your search" : tab === "active" ? "No videos in production" : "No published videos"}
          </p>
        </GlassCard>
      )}

      {/* Video grid */}
      {!isLoading && displayVideos.length > 0 && (
        <motion.div
          variants={container}
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
        >
          {displayVideos.map((video: any) => {
            const progress = statusToProgress(video.status || "");
            const title = video.video_title || "Untitled";
            const status = video.status || "idea_logged";

            return (
              <motion.div key={video.id} variants={item}>
                <Link href={`/pipeline/${video.id}`}>
                  <GlassCard hover className="p-0 overflow-hidden cursor-pointer">
                    {/* Thumbnail */}
                    <div
                      className="aspect-video relative flex items-center justify-center overflow-hidden"
                      style={{
                        background: "var(--bg-elevated)",
                        borderBottom: "1px solid var(--border-subtle)",
                      }}
                    >
                      {video.thumbnail_url ? (
                        <img
                          src={video.thumbnail_url}
                          alt={title}
                          className="absolute inset-0 w-full h-full object-cover"
                        />
                      ) : (
                        <>
                          <div className="absolute inset-0 opacity-10">
                            <svg width="100%" height="100%">
                              <defs>
                                <pattern id={`grid-${video.id}`} width="20" height="20" patternUnits="userSpaceOnUse">
                                  <path d="M 20 0 L 0 0 0 20" fill="none" stroke="var(--turquoise)" strokeWidth="0.5" />
                                </pattern>
                              </defs>
                              <rect width="100%" height="100%" fill={`url(#grid-${video.id})`} />
                            </svg>
                          </div>
                          <Film size={24} style={{ color: "var(--text-tertiary)", opacity: 0.5 }} />
                        </>
                      )}
                    </div>

                    {/* Progress bar */}
                    <div className="h-1" style={{ background: "var(--bg-void)" }}>
                      <div
                        className="h-full transition-all"
                        style={{
                          width: `${progress}%`,
                          background: "var(--turquoise)",
                        }}
                      />
                    </div>

                    {/* Card body */}
                    <div className="p-4">
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <h3
                          className="text-sm font-semibold font-body line-clamp-2"
                          style={{ color: "var(--text-primary)" }}
                        >
                          {title}
                        </h3>
                        <span className="text-[11px] font-mono shrink-0" style={{ color: "var(--text-tertiary)" }}>
                          {progress}%
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <StatusPill
                          label={STATUS_LABEL[status] || status.replace(/_/g, " ")}
                          color={STATUS_COLOR[status] || "turquoise"}
                        />
                        {tab === "published" && video.views > 0 && (
                          <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                            {video.views >= 1000 ? `${(video.views / 1000).toFixed(1)}K` : video.views} views
                          </span>
                        )}
                      </div>
                    </div>
                  </GlassCard>
                </Link>
              </motion.div>
            );
          })}
        </motion.div>
      )}
    </motion.div>
  );
}
