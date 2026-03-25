"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { getVideos, type VideoSummary } from "@/lib/api";
import { VideoCard } from "@/components/video-card";
import { COMPLETED_STATUSES } from "@/lib/constants";
import { Search, Plus, ChevronDown, ChevronRight } from "lucide-react";

export default function PipelinePage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [showUploaded, setShowUploaded] = useState(false);

  const { data: allVideos = [], isLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  // Split into active production vs completed/uploaded
  const { activeVideos, completedVideos } = useMemo(() => {
    let all = [...allVideos];

    // Search filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      all = all.filter((v) => (v.video_title || "").toLowerCase().includes(q));
    }

    // Sort by newest first
    all.sort((a, b) => {
      const da = a.updated_at ? new Date(a.updated_at).getTime() : 0;
      const db = b.updated_at ? new Date(b.updated_at).getTime() : 0;
      return db - da;
    });

    const active: VideoSummary[] = [];
    const completed: VideoSummary[] = [];
    for (const v of all) {
      if (COMPLETED_STATUSES.has(v.status || "")) {
        completed.push(v);
      } else {
        active.push(v);
      }
    }
    return { activeVideos: active, completedVideos: completed };
  }, [allVideos, searchQuery]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>Pipeline</h1>
        <Link
          href="/create"
          className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-opacity hover:opacity-90"
          style={{ backgroundColor: "var(--amber)", color: "var(--bg-primary)" }}
        >
          <Plus size={16} />
          New
        </Link>
      </div>

      {/* Search */}
      <div className="relative">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2"
          style={{ color: "var(--text-secondary)" }}
        />
        <input
          type="text"
          placeholder="Search videos..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded-lg py-2 pl-9 pr-3 text-sm outline-none"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
          }}
        />
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl" style={{ background: "var(--bg-card)" }} />
          ))}
        </div>
      )}

      {/* In Production */}
      {!isLoading && (
        <>
          <div>
            <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--text-secondary)" }}>
              In Production ({activeVideos.length})
            </h2>
            {activeVideos.length > 0 ? (
              <div className="space-y-2">
                {activeVideos.map((video) => (
                  <VideoCard key={video.id} video={video} />
                ))}
              </div>
            ) : (
              <div
                className="flex h-24 items-center justify-center rounded-xl"
                style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
              >
                <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                  {searchQuery ? `No active videos matching "${searchQuery}"` : "No videos in production"}
                </p>
              </div>
            )}
          </div>

          {/* Uploaded / Completed — collapsible */}
          {completedVideos.length > 0 && (
            <div>
              <button
                onClick={() => setShowUploaded(!showUploaded)}
                className="flex items-center gap-2 text-sm font-semibold mb-3"
                style={{ color: "var(--text-muted)" }}
              >
                {showUploaded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                Uploaded ({completedVideos.length})
              </button>
              {showUploaded && (
                <div className="space-y-2">
                  {completedVideos.map((video) => (
                    <VideoCard key={video.id} video={video} />
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
