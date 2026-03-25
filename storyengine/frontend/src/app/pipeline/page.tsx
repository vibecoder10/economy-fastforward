"use client";

import { useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { Search, Film } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { MOCK_VIDEOS } from "@/lib/mock-data";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08 } },
};

const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const STATUS_LABEL: Record<string, string> = {
  idea_logged: "Idea",
  researching: "Researching",
  scripting: "Scripting",
  voice: "Voice",
  visuals: "Visuals",
  storyboard_review: "Storyboard",
  rendering: "Rendering",
  uploaded: "Uploaded",
  published: "Published",
  done: "Published",
};

const STATUS_COLOR: Record<string, string> = {
  idea_logged: "turquoise",
  researching: "turquoise",
  scripting: "orange",
  voice: "green",
  visuals: "purple",
  storyboard_review: "turquoise",
  rendering: "red",
  uploaded: "gold",
  published: "green",
  done: "green",
};

export default function QueuePage() {
  const [search, setSearch] = useState("");

  const filtered = MOCK_VIDEOS.filter((v) =>
    v.title.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between gap-4">
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

      {/* Video grid */}
      <motion.div
        variants={container}
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
      >
        {filtered.map((video) => (
          <motion.div key={video.id} variants={item}>
            <Link href={`/pipeline/${video.id}`}>
              <GlassCard hover className="p-0 overflow-hidden cursor-pointer">
                {/* Thumbnail placeholder */}
                <div
                  className="aspect-video relative flex items-center justify-center"
                  style={{
                    background: "var(--bg-elevated)",
                    borderBottom: "1px solid var(--border-subtle)",
                  }}
                >
                  {/* Holographic grid lines */}
                  <div className="absolute inset-0 opacity-10">
                    <svg width="100%" height="100%" className="absolute inset-0">
                      <defs>
                        <pattern id={`grid-${video.id}`} width="20" height="20" patternUnits="userSpaceOnUse">
                          <path d="M 20 0 L 0 0 0 20" fill="none" stroke="var(--turquoise)" strokeWidth="0.5" />
                        </pattern>
                      </defs>
                      <rect width="100%" height="100%" fill={`url(#grid-${video.id})`} />
                    </svg>
                  </div>
                  <Film size={24} style={{ color: "var(--text-tertiary)", opacity: 0.5 }} />
                </div>

                {/* Progress bar */}
                <div className="h-1" style={{ background: "var(--bg-void)" }}>
                  <div
                    className="h-full transition-all"
                    style={{
                      width: `${video.progress || 0}%`,
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
                      {video.title}
                    </h3>
                    <span className="text-[11px] font-mono shrink-0" style={{ color: "var(--text-tertiary)" }}>
                      {video.progress || 0}%
                    </span>
                  </div>
                  <StatusPill
                    label={STATUS_LABEL[video.status] || video.status}
                    color={STATUS_COLOR[video.status] || "turquoise"}
                  />
                </div>
              </GlassCard>
            </Link>
          </motion.div>
        ))}
      </motion.div>
    </motion.div>
  );
}
