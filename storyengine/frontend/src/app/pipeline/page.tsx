"use client";
import { Spinner } from "@/components/ui/spinner";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search, Film, Loader2, Plus, Clock, Eye, BarChart3,
  RefreshCw, Sparkles, X, ChevronRight, ExternalLink, TrendingUp, Brain, Trash2, GripVertical,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove, SortableContext, sortableKeyboardCoordinates,
  horizontalListSortingStrategy, useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorCard } from "@/components/ui/ErrorCard";
import {
  getVideos, createVideo, deleteVideo,
  getDiscoveryIdeas, getDiscoveryStatus, refreshDiscoveryIdeas,
  launchIdea, dismissIdea, getUserPreferences, setUserPreference,
  type VideoSummary, type DiscoveryIdea, type TitleOption,
} from "@/lib/api";
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

type TabId = "ideas" | "active" | "published";

const DEFAULT_TAB_ORDER: TabId[] = ["ideas", "active", "published"];

function SortableTab({
  id, label, count, icon: Icon, isActive, onClick,
}: {
  id: string;
  label: string;
  count: number;
  icon?: React.ComponentType<{ size?: number }>;
  isActive: boolean;
  onClick: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    color: isActive ? "var(--turquoise)" : "var(--text-tertiary)",
    background: isActive ? "var(--turquoise-bg)" : "transparent",
    borderBottom: isActive ? "2px solid var(--turquoise)" : "2px solid transparent",
  };

  return (
    <button
      ref={setNodeRef}
      style={style}
      {...attributes}
      onClick={onClick}
      className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium font-body transition-all rounded-t-lg"
    >
      <span {...listeners} className="cursor-grab active:cursor-grabbing touch-none">
        <GripVertical size={12} style={{ opacity: 0.4 }} />
      </span>
      {Icon && <Icon size={14} />}
      {label}
      <span
        className="text-[10px] font-mono px-1.5 py-0.5 rounded-full"
        style={{
          background: isActive ? "var(--turquoise-dim)" : "rgba(255,255,255,0.05)",
          color: isActive ? "var(--turquoise)" : "var(--text-tertiary)",
        }}
      >
        {count}
      </span>
    </button>
  );
}

export default function VideosPage() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<TabId>("active");
  const [statusFilter, setStatusFilter] = useState("");

  // Create modal state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newSourceUrl, setNewSourceUrl] = useState("");
  const [newFramework, setNewFramework] = useState("");
  const [newLength, setNewLength] = useState(10);
  const [newGuidance, setNewGuidance] = useState("");
  const [newVisualStyle, setNewVisualStyle] = useState("");
  const [newAccentColor, setNewAccentColor] = useState("");

  // Tab order (drag-to-reorder with persistence)
  const [tabOrder, setTabOrder] = useState<TabId[]>(DEFAULT_TAB_ORDER);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  // Load saved tab order from preferences
  const { data: prefs } = useQuery({
    queryKey: ["user-preferences"],
    queryFn: getUserPreferences,
    staleTime: 60000,
    retry: false,
  });

  useEffect(() => {
    const savedPref = prefs?.pipeline_tab_order as { order?: TabId[] } | TabId[] | undefined;
    const savedOrder = savedPref && typeof savedPref === "object" && !Array.isArray(savedPref) ? savedPref.order : Array.isArray(savedPref) ? savedPref : undefined;
    if (savedOrder && Array.isArray(savedOrder)) {
      const saved = savedOrder;
      if (saved.length === DEFAULT_TAB_ORDER.length && saved.every((t) => DEFAULT_TAB_ORDER.includes(t))) {
        setTabOrder(saved);
      }
    }
  }, [prefs]);

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event;
    if (over && active.id !== over.id) {
      setTabOrder((prev) => {
        const oldIndex = prev.indexOf(active.id as TabId);
        const newIndex = prev.indexOf(over.id as TabId);
        const newOrder = arrayMove(prev, oldIndex, newIndex);
        // Persist to backend (fire-and-forget)
        setUserPreference("pipeline_tab_order", { order: newOrder }).catch(() => {});
        return newOrder;
      });
    }
  }, []);

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<VideoSummary | null>(null);

  // Edit-before-launch modal
  const [editIdea, setEditIdea] = useState<DiscoveryIdea | null>(null);
  const [editTitleIndex, setEditTitleIndex] = useState(0);
  const [editLength, setEditLength] = useState(15);

  // Data
  const { data: videos, isLoading: videosLoading, error: videosError } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  const { data: ideas, isLoading: ideasLoading } = useQuery({
    queryKey: ["discoveryIdeas"],
    queryFn: () => getDiscoveryIdeas("fresh"),
    enabled: tab === "ideas",
  });

  const { data: discoveryStatus } = useQuery({
    queryKey: ["discoveryStatus"],
    queryFn: getDiscoveryStatus,
    enabled: tab === "ideas",
    refetchInterval: 5000,
  });

  // Mutations
  const createMutation = useMutation({
    mutationFn: createVideo,
    onSuccess: (newVideo) => {
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      setShowCreateModal(false);
      setNewTitle("");
      setNewSourceUrl("");
      setNewFramework("");
      setNewLength(10);
      setNewGuidance("");
      setNewVisualStyle("");
      setNewAccentColor("");
      router.push(`/pipeline/${newVideo.id}`);
    },
  });

  const refreshMutation = useMutation({
    mutationFn: refreshDiscoveryIdeas,
    onSuccess: () => {
      // Poll for completion
      const interval = setInterval(async () => {
        const status = await getDiscoveryStatus();
        if (!status.is_refreshing) {
          clearInterval(interval);
          queryClient.invalidateQueries({ queryKey: ["discoveryIdeas"] });
          queryClient.invalidateQueries({ queryKey: ["discoveryStatus"] });
        }
      }, 3000);
    },
  });

  const launchMutation = useMutation({
    mutationFn: ({ ideaId, titleIndex, length }: { ideaId: string; titleIndex: number; length: number }) =>
      launchIdea(ideaId, titleIndex, length),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["discoveryIdeas"] });
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      setEditIdea(null);
      router.push(`/pipeline/${result.video_id}`);
    },
  });

  const dismissMutation = useMutation({
    mutationFn: dismissIdea,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["discoveryIdeas"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteVideo,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      setDeleteTarget(null);
    },
  });

  const handleCreate = () => {
    if (!newTitle.trim()) return;
    createMutation.mutate({
      title: newTitle.trim(),
      source_url: newSourceUrl.trim() || undefined,
      framework_angle: newFramework || undefined,
      video_length_minutes: newLength,
      writer_guidance: newGuidance.trim() || undefined,
      visual_style: newVisualStyle || undefined,
      accent_color: newAccentColor || undefined,
    });
  };

  // Filtered videos
  const allVideos = (videos || []).filter((v: VideoSummary) =>
    (v.video_title || "").toLowerCase().includes(search.toLowerCase())
  );
  const activeVideos = allVideos
    .filter((v) => !COMPLETED_STATUSES.has(v.status || ""))
    .filter((v) => !statusFilter || v.status === statusFilter);
  const publishedVideos = allVideos.filter((v) => COMPLETED_STATUSES.has(v.status || ""));

  const isRefreshing = discoveryStatus?.is_refreshing || refreshMutation.isPending;

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-3xl sm:text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Videos
        </h1>
        <div className="flex items-center gap-2 sm:gap-3 flex-1 justify-end min-w-0">
          {/* Search (active/published tabs) */}
          {tab !== "ideas" && (
            <div className="relative sm:max-w-xs flex-1 min-w-0">
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
          )}

          {/* Status Filter (active tab) */}
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

          {/* Refresh button (ideas tab) */}
          {tab === "ideas" && (
            <button
              onClick={() => refreshMutation.mutate()}
              disabled={isRefreshing}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-50"
              style={{
                background: "var(--bg-elevated)",
                color: "var(--turquoise)",
                border: "1px solid var(--border)",
              }}
            >
              <RefreshCw size={16} className={isRefreshing ? "animate-spin" : ""} />
              {isRefreshing ? "Generating..." : "Refresh Ideas"}
            </button>
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

      {/* Tabs — drag-to-reorder */}
      <motion.div variants={item} className="flex gap-1 overflow-x-auto" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={tabOrder} strategy={horizontalListSortingStrategy}>
            {tabOrder.map((tabId) => {
              const tabConfig: Record<TabId, { label: string; count: number; icon?: React.ComponentType<{ size?: number }> }> = {
                ideas: { label: "Daily Ideas", count: ideas?.length || 0, icon: Sparkles },
                active: { label: "In Production", count: activeVideos.length },
                published: { label: "Published", count: publishedVideos.length },
              };
              const t = tabConfig[tabId];
              return (
                <SortableTab
                  key={tabId}
                  id={tabId}
                  label={t.label}
                  count={t.count}
                  icon={t.icon}
                  isActive={tab === tabId}
                  onClick={() => setTab(tabId)}
                />
              );
            })}
          </SortableContext>
        </DndContext>
      </motion.div>

      {/* === DAILY IDEAS TAB === */}
      {tab === "ideas" && (
        <>
          {ideasLoading && (
            <div className="flex items-center justify-center py-20">
              <Loader2 size={24} className="animate-spin" style={{ color: "var(--turquoise)" }} />
            </div>
          )}

          {!ideasLoading && (!ideas || ideas.length === 0) && (
            <GlassCard className="p-12 text-center">
              <Sparkles size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
              <p className="text-sm mb-2 font-body" style={{ color: "var(--text-secondary)" }}>
                No ideas yet
              </p>
              <p className="text-xs mb-4 font-body" style={{ color: "var(--text-tertiary)" }}>
                Click &quot;Refresh Ideas&quot; to generate ideas from your competitor data, or use &quot;New Video&quot; to create a video from scratch.
              </p>
              <button
                onClick={() => refreshMutation.mutate()}
                disabled={isRefreshing}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-50"
                style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
              >
                <RefreshCw size={16} className={isRefreshing ? "animate-spin" : ""} />
                {isRefreshing ? "Generating..." : "Generate Ideas"}
              </button>
            </GlassCard>
          )}

          {!ideasLoading && ideas && ideas.length > 0 && (
            <motion.div
              variants={container}
              className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
            >
              {ideas.map((idea) => (
                <IdeaCard
                  key={idea.id}
                  idea={idea}
                  onLaunch={(titleIndex) => {
                    launchMutation.mutate({ ideaId: idea.id, titleIndex, length: 15 });
                  }}
                  onEdit={() => {
                    setEditIdea(idea);
                    setEditTitleIndex(0);
                    setEditLength(15);
                  }}
                  onDismiss={() => dismissMutation.mutate(idea.id)}
                  isLaunching={launchMutation.isPending}
                />
              ))}
            </motion.div>
          )}

          {discoveryStatus && (discoveryStatus.last_batch_date || discoveryStatus.learnings_applied > 0) && (
            <div className="flex items-center justify-center gap-4 flex-wrap">
              {discoveryStatus.learnings_applied > 0 && (
                <span
                  className="inline-flex items-center gap-1.5 text-[11px] font-mono px-3 py-1 rounded-full"
                  style={{
                    color: "var(--turquoise)",
                    background: "rgba(0, 245, 212, 0.06)",
                    border: "1px solid rgba(0, 245, 212, 0.12)",
                  }}
                >
                  <Brain size={12} />
                  {discoveryStatus.learnings_applied} learnings influencing ideas
                </span>
              )}
              {discoveryStatus.last_batch_date && (
                <p className="text-xs font-body" style={{ color: "var(--text-tertiary)" }}>
                  Last generated: {discoveryStatus.last_batch_date}
                </p>
              )}
            </div>
          )}
        </>
      )}

      {/* === IN PRODUCTION / PUBLISHED TABS === */}
      {(tab === "active" || tab === "published") && (
        <>
          {videosLoading && (
            <div className="flex items-center justify-center py-20">
              <Spinner size="lg" />
            </div>
          )}

          {videosError && !videosLoading && (
            <ErrorCard message={(videosError as Error).message} onRetry={() => window.location.reload()} />
          )}

          {!videosLoading && (tab === "active" ? activeVideos : publishedVideos).length === 0 && (
            <EmptyState
              icon={Film}
              title={search
                ? "No videos match your search"
                : statusFilter
                ? "No videos at this stage"
                : tab === "active"
                ? "No videos in production"
                : "No published videos"}
              description={tab === "active" && !search && !statusFilter ? "Start by creating a new video or browsing discovery ideas." : undefined}
              actionLabel={tab === "active" && !search && !statusFilter ? "Browse Ideas" : undefined}
              onAction={tab === "active" && !search && !statusFilter ? () => setTab("ideas") : undefined}
            />
          )}

          {!videosLoading && (tab === "active" ? activeVideos : publishedVideos).length > 0 && (
            <motion.div
              variants={container}
              className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
            >
              {(tab === "active" ? activeVideos : publishedVideos).map((video: VideoSummary) => {
                const progress = statusToProgress(video.status || "");
                const title = video.video_title || "Untitled";
                const status = video.status || "idea_logged";
                const isPublished = COMPLETED_STATUSES.has(status);

                return (
                  <motion.div key={video.id} variants={item} className="group relative">
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
                                (e.target as HTMLImageElement).style.display = "none";
                              }}
                            />
                          )}
                        </div>

                        {/* Progress bar */}
                        <div className="h-1" style={{ background: "var(--bg-void)" }}>
                          <div
                            className="h-full transition-all"
                            style={{ width: `${progress}%`, background: "var(--turquoise)" }}
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
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setDeleteTarget(video);
                      }}
                      className="absolute top-2 right-2 p-1.5 rounded-md opacity-0 group-hover:opacity-100 transition-all z-10"
                      style={{ background: "rgba(0,0,0,0.7)", color: "var(--red, #ef4444)" }}
                      title="Delete video"
                    >
                      <Trash2 size={14} />
                    </button>
                  </motion.div>
                );
              })}
            </motion.div>
          )}
        </>
      )}

      {/* === DELETE CONFIRMATION MODAL === */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Video"
        size="sm"
      >
        {deleteTarget && (
          <div className="space-y-4">
            <p className="text-sm font-body" style={{ color: "var(--text-secondary)" }}>
              Are you sure you want to delete{" "}
              <strong style={{ color: "var(--text-primary)" }}>
                {deleteTarget.video_title || "Untitled"}
              </strong>
              ? This action can be undone by an admin.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setDeleteTarget(null)}
                className="flex-1 py-2.5 rounded-lg text-sm font-medium transition-all"
                style={{
                  background: "var(--bg-elevated)",
                  color: "var(--text-secondary)",
                  border: "1px solid var(--border)",
                }}
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate(deleteTarget.id)}
                disabled={deleteMutation.isPending}
                className="flex-1 py-2.5 rounded-lg text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-50"
                style={{ background: "var(--red, #ef4444)", color: "white" }}
              >
                {deleteMutation.isPending ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 size={14} className="animate-spin" /> Deleting...
                  </span>
                ) : (
                  "Delete"
                )}
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* === NEW VIDEO MODAL === */}
      <Modal open={showCreateModal} onClose={() => setShowCreateModal(false)} title="New Video" size="md">
        <div className="space-y-4">
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

          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
              Angle / Thesis <span style={{ color: "var(--text-tertiary)" }}>(optional)</span>
            </label>
            <textarea
              value={newGuidance}
              onChange={(e) => setNewGuidance(e.target.value)}
              placeholder="What angle should the script take? e.g. Focus on the economic consequences, use a contrarian tone..."
              rows={3}
              className="w-full px-3 py-2.5 rounded-lg text-sm font-body outline-none resize-none"
              style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                Framework
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

          {/* Visual Style */}
          <div>
            <label className="block text-xs font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
              Visual Style
            </label>
            <div className="grid grid-cols-2 gap-2">
              {[
                { id: "cinematic_illustration", label: "Cinematic Illustration", desc: "Editorial, warm tones" },
                { id: "holographic_hud", label: "Holographic HUD", desc: "Data overlays, neon" },
                { id: "cinematic_dossier", label: "Cinematic Dossier", desc: "Photorealistic, dramatic" },
                { id: "clay_mannequin", label: "Clay Mannequin", desc: "3D clay, faceless figures" },
              ].map((style) => (
                <button
                  key={style.id}
                  type="button"
                  onClick={() => setNewVisualStyle(newVisualStyle === style.id ? "" : style.id)}
                  className="text-left px-3 py-2.5 rounded-lg transition-all text-xs"
                  style={{
                    background: newVisualStyle === style.id ? "rgba(0,212,170,0.1)" : "var(--bg-elevated)",
                    border: `1px solid ${newVisualStyle === style.id ? "var(--turquoise)" : "var(--border)"}`,
                    color: "var(--text-primary)",
                  }}
                >
                  <div className="font-medium">{style.label}</div>
                  <div style={{ color: "var(--text-tertiary)", fontSize: "10px" }}>{style.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Accent Color */}
          <div>
            <label className="block text-xs font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
              Accent Color
            </label>
            <div className="flex gap-2">
              {[
                { id: "cold teal", hex: "#1A8A7A", label: "Teal" },
                { id: "muted crimson", hex: "#8B2252", label: "Crimson" },
                { id: "warm amber", hex: "#D4A844", label: "Amber" },
                { id: "muted green", hex: "#4A7A5A", label: "Green" },
              ].map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setNewAccentColor(newAccentColor === c.id ? "" : c.id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all text-xs"
                  style={{
                    background: newAccentColor === c.id ? "rgba(255,255,255,0.08)" : "var(--bg-elevated)",
                    border: `1px solid ${newAccentColor === c.id ? c.hex : "var(--border)"}`,
                    color: "var(--text-primary)",
                  }}
                >
                  <span className="inline-block w-3 h-3 rounded-full" style={{ background: c.hex }} />
                  {c.label}
                </button>
              ))}
            </div>
          </div>

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

      {/* === EDIT & LAUNCH MODAL === */}
      <Modal
        open={!!editIdea}
        onClose={() => setEditIdea(null)}
        title="Review & Launch"
        size="md"
      >
        {editIdea && (
          <div className="space-y-4">
            {/* Competitor source */}
            {editIdea.competitor_title && (
              <div
                className="p-3 rounded-lg text-xs font-body"
                style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
              >
                <span style={{ color: "var(--text-tertiary)" }}>Inspired by: </span>
                <span style={{ color: "var(--text-secondary)" }}>
                  &quot;{editIdea.competitor_title}&quot;
                </span>
                {editIdea.competitor_channel && (
                  <span style={{ color: "var(--text-tertiary)" }}> by {editIdea.competitor_channel}</span>
                )}
              </div>
            )}

            {/* Our angle */}
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                Our Angle
              </label>
              <p className="text-sm font-body" style={{ color: "var(--text-primary)" }}>
                {editIdea.our_angle}
              </p>
            </div>

            {/* Title selection */}
            <div>
              <label className="block text-xs font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
                Select Title
              </label>
              <div className="space-y-2">
                {editIdea.title_options.map((opt: TitleOption, idx: number) => (
                  <button
                    key={idx}
                    onClick={() => setEditTitleIndex(idx)}
                    className="w-full text-left p-3 rounded-lg text-sm font-body transition-all"
                    style={{
                      background: editTitleIndex === idx ? "var(--turquoise-bg)" : "var(--bg-elevated)",
                      border: `1px solid ${editTitleIndex === idx ? "var(--turquoise)" : "var(--border)"}`,
                      color: "var(--text-primary)",
                    }}
                  >
                    <div className="flex items-center justify-between">
                      <span>{opt.title}</span>
                      {opt.score > 0 && (
                        <span className="text-[10px] font-mono" style={{ color: "var(--turquoise)" }}>
                          {opt.score}/10
                        </span>
                      )}
                    </div>
                    {opt.thumbnail_text && (
                      <span className="text-[10px] mt-1 block" style={{ color: "var(--text-tertiary)" }}>
                        Thumbnail: {opt.thumbnail_text}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* Video length */}
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                Video Length
              </label>
              <div className="flex gap-2">
                {[5, 10, 15, 20].map((mins) => (
                  <button
                    key={mins}
                    onClick={() => setEditLength(mins)}
                    className="px-4 py-2 rounded-full text-sm font-medium font-body transition-all"
                    style={{
                      background: editLength === mins ? "var(--turquoise)" : "var(--bg-elevated)",
                      color: editLength === mins ? "var(--bg-void)" : "var(--text-secondary)",
                      border: `1px solid ${editLength === mins ? "var(--turquoise)" : "var(--border)"}`,
                    }}
                  >
                    {mins} min
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={() =>
                launchMutation.mutate({
                  ideaId: editIdea.id,
                  titleIndex: editTitleIndex,
                  length: editLength,
                })
              }
              disabled={launchMutation.isPending}
              className="w-full py-2.5 rounded-lg text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-40"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              {launchMutation.isPending ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 size={14} className="animate-spin" /> Launching...
                </span>
              ) : (
                "Launch Video"
              )}
            </button>
          </div>
        )}
      </Modal>
    </motion.div>
  );
}


// === IDEA CARD COMPONENT ===

function IdeaCard({
  idea,
  onLaunch,
  onEdit,
  onDismiss,
  isLaunching,
}: {
  idea: DiscoveryIdea;
  onLaunch: (titleIndex: number) => void;
  onEdit: () => void;
  onDismiss: () => void;
  isLaunching: boolean;
}) {
  const [selectedTitle, setSelectedTitle] = useState(0);

  return (
    <motion.div variants={item}>
      <GlassCard className="p-0 overflow-hidden">
        {/* Thumbnail / Source header */}
        <div
          className="relative h-32 flex items-end overflow-hidden"
          style={{ background: "var(--bg-elevated)" }}
        >
          {idea.competitor_thumbnail_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={idea.competitor_thumbnail_url}
              alt=""
              className="absolute inset-0 w-full h-full object-cover opacity-40"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          )}
          <div className="absolute inset-0" style={{ background: "linear-gradient(transparent 30%, var(--bg-deep) 100%)" }} />

          {/* VPH badge */}
          {idea.competitor_vph && idea.competitor_vph > 0 && (
            <div
              className="absolute top-2 right-2 px-2 py-1 rounded-md text-[10px] font-mono font-bold flex items-center gap-1"
              style={{ background: "rgba(0,0,0,0.7)", color: "var(--turquoise)" }}
            >
              <TrendingUp size={10} />
              {idea.competitor_vph >= 1000
                ? `${(idea.competitor_vph / 1000).toFixed(1)}K`
                : Math.round(idea.competitor_vph)}{" "}
              VPH
            </div>
          )}

          {/* Dismiss */}
          <button
            onClick={(e) => { e.stopPropagation(); onDismiss(); }}
            className="absolute top-2 left-2 p-1 rounded-md transition-all hover:brightness-150"
            style={{ background: "rgba(0,0,0,0.5)", color: "var(--text-tertiary)" }}
            title="Dismiss idea"
          >
            <X size={12} />
          </button>

          {/* Source info */}
          <div className="relative z-10 px-4 pb-3 w-full">
            {idea.competitor_channel && (
              <p className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                {idea.competitor_channel}
              </p>
            )}
            {idea.competitor_title && (
              <p className="text-xs font-body line-clamp-1" style={{ color: "var(--text-secondary)" }}>
                {idea.competitor_title}
              </p>
            )}
          </div>
        </div>

        {/* Body */}
        <div className="p-4 space-y-3">
          {/* Our angle */}
          <p className="text-sm font-body line-clamp-3" style={{ color: "var(--text-primary)" }}>
            {idea.our_angle}
          </p>

          {/* Framework + Appeal */}
          <div className="flex items-center gap-2 flex-wrap">
            {idea.framework && (
              <StatusPill label={idea.framework} color="purple" />
            )}
            {idea.estimated_appeal && (
              <span
                className="text-[10px] font-mono px-2 py-0.5 rounded-full"
                style={{
                  background: idea.estimated_appeal >= 7
                    ? "rgba(0, 230, 138, 0.12)"
                    : idea.estimated_appeal >= 5
                    ? "rgba(255, 186, 8, 0.12)"
                    : "rgba(255,255,255,0.05)",
                  color: idea.estimated_appeal >= 7
                    ? "var(--green)"
                    : idea.estimated_appeal >= 5
                    ? "var(--gold)"
                    : "var(--text-tertiary)",
                }}
              >
                Appeal: {idea.estimated_appeal}/10
              </span>
            )}
          </div>

          {/* Title options */}
          {idea.title_options.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>
                Title Options
              </p>
              {idea.title_options.map((opt: TitleOption, idx: number) => (
                <button
                  key={idx}
                  onClick={() => setSelectedTitle(idx)}
                  className="w-full text-left px-3 py-2 rounded-lg text-xs font-body transition-all flex items-center justify-between gap-2"
                  style={{
                    background: selectedTitle === idx ? "var(--turquoise-bg)" : "transparent",
                    border: `1px solid ${selectedTitle === idx ? "var(--turquoise)" : "var(--border-subtle)"}`,
                    color: selectedTitle === idx ? "var(--turquoise)" : "var(--text-secondary)",
                  }}
                >
                  <span className="line-clamp-1">{opt.title}</span>
                  {opt.score > 0 && (
                    <span className="text-[9px] font-mono shrink-0 opacity-70">{opt.score}/10</span>
                  )}
                </button>
              ))}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            <button
              onClick={() => onLaunch(selectedTitle)}
              disabled={isLaunching}
              className="flex-1 py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 disabled:opacity-40 flex items-center justify-center gap-1.5"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              {isLaunching ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <ChevronRight size={12} />
              )}
              Generate Video
            </button>
            <button
              onClick={onEdit}
              className="px-3 py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110"
              style={{
                background: "var(--bg-elevated)",
                color: "var(--text-secondary)",
                border: "1px solid var(--border)",
              }}
            >
              Edit
            </button>
          </div>
        </div>
      </GlassCard>
    </motion.div>
  );
}
