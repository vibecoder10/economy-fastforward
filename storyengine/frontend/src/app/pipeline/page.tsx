"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { getVideos, type VideoSummary } from "@/lib/api";
import { VideoCard } from "@/components/video-card";
import { Search, Plus } from "lucide-react";

// Status filter options
const STATUS_FILTERS = [
  { value: "all", label: "All" },
  { value: "in_progress", label: "In Progress" },
  { value: "needs_approval", label: "Needs Approval" },
  { value: "done", label: "Done" },
];

// Sort options
const SORT_OPTIONS = [
  { value: "newest", label: "Newest" },
  { value: "oldest", label: "Oldest" },
  { value: "views", label: "Most Views" },
  { value: "ctr", label: "Highest CTR" },
];

// Statuses that count as "in progress"
const IN_PROGRESS_STATUSES = new Set([
  "ready_for_scripting",
  "ready_for_voice",
  "ready_for_storyboards",
  "ready_for_images",
  "ready_for_thumbnail",
  "ready_to_render",
  "rendered",
]);

// Statuses that count as "needs approval"
const NEEDS_APPROVAL_STATUSES = new Set([
  "ready_for_scripting",
  "ready_for_storyboards",
  "ready_for_thumbnail",
]);

export default function PipelinePage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortBy, setSortBy] = useState("newest");
  const [searchQuery, setSearchQuery] = useState("");

  // Fetch all videos (no server-side filter — we filter client-side for the new categories)
  const { data: allVideos = [], isLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  // Filter and sort videos client-side
  const videos = useMemo(() => {
    let filtered = [...allVideos];

    // Search filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter((v) =>
        (v.video_title || "").toLowerCase().includes(q)
      );
    }

    // Status filter
    if (statusFilter === "in_progress") {
      filtered = filtered.filter((v) => IN_PROGRESS_STATUSES.has(v.status || ""));
    } else if (statusFilter === "needs_approval") {
      filtered = filtered.filter((v) => NEEDS_APPROVAL_STATUSES.has(v.status || ""));
    } else if (statusFilter === "done") {
      filtered = filtered.filter((v) => v.status === "done" || v.status === "uploaded_draft");
    }

    // Sort
    if (sortBy === "newest") {
      filtered.sort((a, b) => {
        const da = a.created_at ? new Date(a.created_at).getTime() : 0;
        const db = b.created_at ? new Date(b.created_at).getTime() : 0;
        return db - da;
      });
    } else if (sortBy === "oldest") {
      filtered.sort((a, b) => {
        const da = a.created_at ? new Date(a.created_at).getTime() : 0;
        const db = b.created_at ? new Date(b.created_at).getTime() : 0;
        return da - db;
      });
    } else if (sortBy === "views") {
      filtered.sort((a, b) => (b.views || 0) - (a.views || 0));
    } else if (sortBy === "ctr") {
      filtered.sort((a, b) => (b.ctr ?? -1) - (a.ctr ?? -1));
    }

    return filtered;
  }, [allVideos, searchQuery, statusFilter, sortBy]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Pipeline</h1>
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
          className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]"
        />
        <input
          type="text"
          placeholder="Search videos..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-card)] py-2 pl-9 pr-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:ring-1 focus:ring-[var(--border)]"
        />
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--border)]"
        >
          {STATUS_FILTERS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--border)]"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
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
            {searchQuery
              ? `No videos matching "${searchQuery}"`
              : statusFilter !== "all"
                ? `No ${STATUS_FILTERS.find((f) => f.value === statusFilter)?.label ?? ""} videos`
                : "No videos"}
          </p>
        </div>
      )}

      {/* Video list */}
      <div className="space-y-2">
        {videos.map((video) => (
          <VideoCard key={video.id} video={video} />
        ))}
      </div>
    </div>
  );
}
