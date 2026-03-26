"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Search, Film, Loader2, Plus, Clock, Eye, BarChart3 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getVideos, createVideo, type VideoSummary } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { Modal } from "@/components/ui/modal";

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
  idea_logged: "Idea Logged",
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

const FILTER_OPTIONS = [
  { value: "", label: "All Stages" },
  { value: "idea_logged", label: "Idea Logged" },
  { value: "ready_for_scripting", label: "Ready for Script" },
  { value: "ready_for_voice", label: "Ready for Voice" },
  { value: "ready_for_image_prompts", label: "Image Prompts" },
  { value: "ready_for_images", label: "Ready for Images" },
  { value: "ready_for_video_scripts", label: "Video Scripts" },
  { value: "ready_for_thumbnail", label: "Thumbnail" },
  { value: "ready_to_render", label: "Ready to Render" },
  { value: "rendered", label: "Rendered" },
];

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

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

const VERDICT_COLORS: Record<string, { bg: string; text: string }> = {
  strong: { bg: "rgba(0, 230, 138, 0.12)", text: "var(--green)" },
  average: { bg: "rgba(255, 186, 8, 0.12)", text: "var(--gold)" },
  weak: { bg: "rgba(255, 120, 73, 0.12)", text: "var(--orange)" },
};

export default function QueuePage() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<"active" | "published">("active");
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Create form state
  const [newTitle, setNewTitle] = useState("");
  const [newSourceUrl, setNewSourceUrl] = useState("");
  const [newFramework, setNewFramework] = useState("");
  const [newLength, setNewLength] = useState(10);

  const { data: videos, isLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  const createMutation = useMutation({
    mutationFn: createVideo,
    onSuccess: (newVideo) => {
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      setShowCreateModal(false);
      setNewTitle("");
      setNewSourceUrl("");
      setNewFramework("");
      setNewLength(10);
      router.push(`/pipeline/${newVideo.id}`);
    },
  });

  const handleCreate = () => {
    if (!newTitle.trim()) return;
    createMutation.mutate({
      title: newTitle.trim(),
      source_url: newSourceUrl.trim() || undefined,
      framework_angle: newFramework || undefined,
      video_length_minutes: newLength,
    });
  };

  const allVideos = (videos || []).filter((v: VideoSummary) =>
    (v.video_title || "").toLowerCase().includes(search.toLowerCase())
  );

  const activeVideos = allVideos
    .filter((v) => !COMPLETED_STATUSES.has(v.status || ""))
    .filter((v) => !statusFilter || v.status === statusFilter);
  const publishedVideos = allVideos.filter((v) => COMPLETED_STATUSES.has(v.status || ""));

  const displayVideos = tab === "active" ? activeVideos : publishedVideos;

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between gap-4 flex-wrap">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Queue
        </h1>
        <div className="flex items-center gap-3 flex-1 justify-end">
          {/* Search */}
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

          {/* Status Filter */}
          {tab === "active" && (
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2 rounded-lg text-sm font-body outline-none"
              style={{
                background: "var(--bg-elevated)",
                color: "var(--text-primary)",
                border: "1px solid var(--border)",
              }}
            >
              {FILTER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          )}

          {/* New Video Button */}
          <button
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all hover:brightness-110 shrink-0"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            <Plus size={16} /> New Video
          </button>
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
          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
            {search
              ? "No videos match your search"
              : statusFilter
              ? "No videos at this stage"
              : tab === "active"
              ? "No videos in production"
              : "No published videos"}
          </p>
          {tab === "active" && !search && !statusFilter && (
            <button
              onClick={() => setShowCreateModal(true)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all hover:brightness-110"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              <Plus size={16} /> Create Your First Video
            </button>
          )}
        </GlassCard>
      )}

      {/* Video grid */}
      {!isLoading && displayVideos.length > 0 && (
        <motion.div
          variants={container}
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
        >
          {displayVideos.map((video: VideoSummary) => {
            const progress = statusToProgress(video.status || "");
            const title = video.video_title || "Untitled";
            const status = video.status || "idea_logged";
            const isPublished = COMPLETED_STATUSES.has(status);

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
                      {/* Grid pattern fallback (always rendered, thumbnail covers it when loaded) */}
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
                      {!video.thumbnail_url && (
                        <Film size={24} style={{ color: "var(--text-tertiary)", opacity: 0.5 }} />
                      )}
                      {video.thumbnail_url && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={video.thumbnail_url}
                          alt={title}
                          className="absolute inset-0 w-full h-full object-cover"
                          onError={(e) => {
                            // Hide broken image so grid pattern fallback shows through
                            (e.target as HTMLImageElement).style.display = "none";
                          }}
                        />
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
                        {!isPublished && (
                          <span className="text-[11px] font-mono shrink-0" style={{ color: "var(--text-tertiary)" }}>
                            {progress}%
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <StatusPill
                          label={STATUS_LABEL[status] || status.replace(/_/g, " ")}
                          color={STATUS_COLOR[status] || "turquoise"}
                        />
                        {/* Published tab: performance data */}
                        {isPublished && video.views > 0 && (
                          <span className="flex items-center gap-1 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                            <Eye size={10} />
                            {video.views >= 1000 ? `${(video.views / 1000).toFixed(1)}K` : video.views}
                          </span>
                        )}
                        {isPublished && video.ctr != null && (
                          <span className="flex items-center gap-1 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                            <BarChart3 size={10} />
                            {video.ctr.toFixed(1)}%
                          </span>
                        )}
                        {/* Active tab: time since creation */}
                        {!isPublished && video.created_at && (
                          <span className="flex items-center gap-1 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                            <Clock size={10} />
                            {timeAgo(video.created_at)}
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

      {/* Create New Video Modal */}
      <Modal open={showCreateModal} onClose={() => setShowCreateModal(false)} title="Create New Video" size="md">
        <div className="space-y-4">
          {/* Title */}
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
              Title <span style={{ color: "var(--red)" }}>*</span>
            </label>
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="e.g. Why China's Dollar Trap Changes Everything"
              className="w-full px-3 py-2.5 rounded-lg text-sm font-body outline-none"
              style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              onFocus={(e) => (e.target.style.borderColor = "var(--turquoise)")}
              onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
              autoFocus
            />
          </div>

          {/* Source URL */}
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
              Source URL <span style={{ color: "var(--text-tertiary)" }}>(optional)</span>
            </label>
            <input
              type="text"
              value={newSourceUrl}
              onChange={(e) => setNewSourceUrl(e.target.value)}
              placeholder="https://..."
              className="w-full px-3 py-2.5 rounded-lg text-sm font-body outline-none"
              style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            {/* Framework */}
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                Framework <span style={{ color: "var(--text-tertiary)" }}>(optional)</span>
              </label>
              <select
                value={newFramework}
                onChange={(e) => setNewFramework(e.target.value)}
                className="w-full px-3 py-2.5 rounded-lg text-sm font-body outline-none"
                style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              >
                <option value="">None</option>
                <option value="Machiavellian Power Analysis">Machiavellian Power</option>
                <option value="Systems Thinking">Systems Thinking</option>
                <option value="Game Theory">Game Theory</option>
                <option value="Historical Parallel">Historical Parallel</option>
                <option value="Economic Analysis">Economic Analysis</option>
              </select>
            </div>

            {/* Video Length */}
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                Video Length
              </label>
              <select
                value={newLength}
                onChange={(e) => setNewLength(Number(e.target.value))}
                className="w-full px-3 py-2.5 rounded-lg text-sm font-body outline-none"
                style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              >
                {[5, 8, 10, 12, 15, 20].map((n) => (
                  <option key={n} value={n}>{n} minutes</option>
                ))}
              </select>
            </div>
          </div>

          {/* Create button */}
          <button
            onClick={handleCreate}
            disabled={!newTitle.trim() || createMutation.isPending}
            className="w-full py-2.5 rounded-lg text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-40"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            {createMutation.isPending ? (
              <span className="flex items-center justify-center gap-2">
                <Loader2 size={14} className="animate-spin" /> Creating...
              </span>
            ) : (
              "Create Video"
            )}
          </button>

          {createMutation.isError && (
            <p className="text-xs text-center" style={{ color: "var(--red)" }}>
              {(createMutation.error as Error).message}
            </p>
          )}
        </div>
      </Modal>
    </motion.div>
  );
}
