"use client";

import { useState, useEffect, useRef } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Filter, Plus, Loader2, RefreshCw, X, ChevronDown, ChevronLeft, ChevronRight, AlertTriangle, StopCircle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import { Modal } from "@/components/ui/modal";
import { NicheSetup } from "@/components/autopilot/niche-setup";
import {
  getNicheConfig,
  getNicheChannels,
  getNicheVideos,
  addNicheChannel,
  removeNicheChannel,
  createVideo,
  scrapeCompetitorChannels,
  getScrapeStatus,
  cancelScrape,
  type NicheVideo,
} from "@/lib/api";
import { formatNumber, timeAgo } from "@/lib/utils";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

type SortOption = "vph_desc" | "vph_asc" | "views_desc" | "published_desc" | "scrape_desc";
const PAGE_SIZE = 24;

function ScrapeErrorLog({ error, lastRun }: { error: string; lastRun: string | null }) {
  const [expanded, setExpanded] = useState(false);

  // Try to parse multi-line or structured error messages
  const errorLines = error.split(/\n|(?<=\.)(?=\s+[A-Z])/).filter(Boolean).map(l => l.trim());
  const hasDetails = errorLines.length > 1;

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{
        background: "rgba(255, 77, 106, 0.06)",
        border: "1px solid rgba(255, 77, 106, 0.2)",
      }}
    >
      <button
        onClick={() => hasDetails && setExpanded(v => !v)}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-left"
        style={{ cursor: hasDetails ? "pointer" : "default" }}
      >
        <AlertTriangle size={14} style={{ color: "var(--red)", flexShrink: 0 }} />
        <span style={{ color: "var(--red)" }} className="flex-1 font-medium">
          Scrape failed: {errorLines[0]}
        </span>
        {lastRun && (
          <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
            {timeAgo(lastRun)}
          </span>
        )}
        {hasDetails && (
          <ChevronDown
            size={14}
            style={{
              color: "var(--text-tertiary)",
              transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
              transition: "transform 0.2s",
              flexShrink: 0,
            }}
          />
        )}
      </button>
      <AnimatePresence>
        {expanded && hasDetails && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div
              className="px-4 pb-3 space-y-1.5"
              style={{ borderTop: "1px solid rgba(255, 77, 106, 0.1)" }}
            >
              {errorLines.slice(1).map((line, i) => (
                <p
                  key={i}
                  className="text-xs font-mono leading-relaxed"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {line}
                </p>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function CompetitorsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [channelFilter, setChannelFilter] = useState("all");
  const [channelUrl, setChannelUrl] = useState("");
  const [addError, setAddError] = useState("");
  const [sortBy, setSortBy] = useState<SortOption>("vph_desc");
  const [page, setPage] = useState(0);

  // "Model This" modal state
  const [modelVideo, setModelVideo] = useState<NicheVideo | null>(null);
  const [modelTitle, setModelTitle] = useState("");
  const [modelFramework, setModelFramework] = useState("");
  const [modelLength, setModelLength] = useState(10);
  const [modelCreating, setModelCreating] = useState(false);

  const { data: nicheConfig } = useQuery({
    queryKey: ["niche-config"],
    queryFn: getNicheConfig,
  });

  const { data: channels } = useQuery({
    queryKey: ["niche-channels"],
    queryFn: getNicheChannels,
  });

  // Server-side paginated + sorted + filtered video list
  const { data: videosData, isLoading } = useQuery({
    queryKey: ["niche-videos", sortBy, channelFilter, page],
    queryFn: () =>
      getNicheVideos({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        sort: sortBy,
        channel: channelFilter === "all" ? undefined : channelFilter,
      }),
  });

  const addChannelMutation = useMutation({
    mutationFn: async (url: string) => {
      const match =
        url.match(/@([^/?]+)/)?.[1] ||
        url.match(/\/c\/([^/?]+)/)?.[1] ||
        url.match(/\/channel\/([^/?]+)/)?.[1];
      const name =
        match || new URL(url).pathname.split("/").filter(Boolean).pop() || "Unknown";
      return addNicheChannel(name, url);
    },
    onSuccess: () => {
      setChannelUrl("");
      queryClient.invalidateQueries({ queryKey: ["niche-channels"] });
      queryClient.invalidateQueries({ queryKey: ["niche-videos"] });
    },
    onError: (err: Error) => {
      setAddError(err.message || "Failed to add channel");
    },
  });

  // Scrape status polling
  const { data: scrapeStatus } = useQuery({
    queryKey: ["scrape-status"],
    queryFn: getScrapeStatus,
    refetchInterval: (query) => {
      if (query.state.data?.is_running) return 3000;
      return false;
    },
  });

  const deleteChannelMutation = useMutation({
    mutationFn: removeNicheChannel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["niche-channels"] });
      queryClient.invalidateQueries({ queryKey: ["niche-videos"] });
    },
  });

  const scrapeMutation = useMutation({
    mutationFn: scrapeCompetitorChannels,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scrape-status"] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: cancelScrape,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scrape-status"] });
    },
  });

  const scrapeRunning = scrapeStatus?.is_running ?? false;
  const scrapeFinished = !scrapeRunning && scrapeStatus?.last_run != null;
  const prevRunning = useRef(false);

  // When scrape transitions from running to done, refresh videos
  useEffect(() => {
    if (prevRunning.current && !scrapeRunning) {
      queryClient.invalidateQueries({ queryKey: ["niche-videos"] });
    }
    prevRunning.current = scrapeRunning;
  }, [scrapeRunning, queryClient]);

  const nicheConfigured = nicheConfig?.niche_category != null;

  // Channel names from API response or channels table
  const channelNames = videosData?.channels ?? [];

  const totalVideos = videosData?.total ?? 0;
  const totalPages = Math.ceil(totalVideos / PAGE_SIZE);
  const videos = videosData?.videos ?? [];

  // Reset page when filter changes
  const handleFilterChange = (value: string) => {
    setChannelFilter(value);
    setPage(0);
  };

  const handleSortChange = (value: string) => {
    setSortBy(value as SortOption);
    setPage(0);
  };

  // Open "Model This" modal
  const openModelModal = (video: NicheVideo) => {
    setModelVideo(video);
    setModelTitle(video.title);
    setModelFramework("");
    setModelLength(10);
    setModelCreating(false);
  };

  // Create video from competitor
  const handleCreateFromVideo = async () => {
    if (!modelVideo) return;
    setModelCreating(true);
    try {
      const video = await createVideo({
        title: modelTitle,
        source_url: modelVideo.url || undefined,
        framework_angle: modelFramework || undefined,
        video_length_minutes: modelLength,
      });
      setModelVideo(null);
      router.push(`/pipeline/${video.id}`);
    } catch (err) {
      console.error("Failed to create video:", err);
      setModelCreating(false);
    }
  };

  if (!nicheConfigured && nicheConfig) {
    return <NicheSetup onComplete={() => queryClient.invalidateQueries({ queryKey: ["niche-config"] })} />;
  }

  if (isLoading && !videosData) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display" style={{ color: "var(--text-primary)" }}>
            Competitor Analysis
          </h1>
          {nicheConfig?.sub_niche && (
            <p className="text-sm mt-1 font-body" style={{ color: "var(--text-secondary)" }}>
              {nicheConfig.niche_category} &middot; {nicheConfig.sub_niche}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {scrapeRunning && (
            <button
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors"
              style={{
                color: "var(--red)",
                border: "1px solid rgba(255, 77, 106, 0.3)",
                background: "rgba(255, 77, 106, 0.08)",
              }}
            >
              <StopCircle size={14} />
              Cancel
            </button>
          )}
          <ActionButton
            icon={scrapeRunning ? undefined : RefreshCw}
            onClick={() => scrapeMutation.mutate()}
            disabled={scrapeRunning || scrapeMutation.isPending}
          >
            {scrapeRunning ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                <span className="ml-1">Scraping...</span>
              </>
            ) : (
              "Scrape Now"
            )}
          </ActionButton>
        </div>
      </motion.div>

      {/* Scrape progress (running) */}
      {scrapeRunning && scrapeStatus && (
        <motion.div variants={item}>
          <GlassCard className="!p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" style={{ color: "var(--turquoise)" }} />
                <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                  Scraping{scrapeStatus.current_channel ? `: ${scrapeStatus.current_channel}` : "..."}
                </span>
              </div>
              <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                {scrapeStatus.channels_done}/{scrapeStatus.channels_total} channels
              </span>
            </div>
            {scrapeStatus.channels_total > 0 && (
              <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-elevated)" }}>
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${(scrapeStatus.channels_done / scrapeStatus.channels_total) * 100}%`,
                    background: "var(--turquoise)",
                  }}
                />
              </div>
            )}
            {Object.keys(scrapeStatus.channel_progress).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(scrapeStatus.channel_progress).map(([name, count]) => (
                  <span
                    key={name}
                    className="text-[10px] px-2 py-0.5 rounded-md font-mono"
                    style={{
                      background: count === -1 ? "rgba(255, 77, 106, 0.1)" : "rgba(0, 212, 170, 0.08)",
                      color: count === -1 ? "var(--red)" : "var(--text-secondary)",
                    }}
                  >
                    {name}: {count === -1 ? "error" : `${count} videos`}
                  </span>
                ))}
              </div>
            )}
          </GlassCard>
        </motion.div>
      )}

      {/* Scrape status banner (finished) */}
      {scrapeFinished && !scrapeStatus?.error && scrapeStatus?.videos_found != null && (
        <motion.div variants={item}>
          <div
            className="rounded-xl px-4 py-2.5 text-sm flex items-center justify-between"
            style={{
              background: "rgba(0, 212, 170, 0.08)",
              border: "1px solid rgba(0, 212, 170, 0.2)",
              color: "var(--turquoise)",
            }}
          >
            <span>
              Last scrape found {scrapeStatus.videos_found} videos ({scrapeStatus.videos_saved} saved)
            </span>
            {scrapeStatus.last_run && (
              <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                {timeAgo(scrapeStatus.last_run)}
              </span>
            )}
          </div>
        </motion.div>
      )}
      {scrapeStatus?.error && !scrapeRunning && (
        <motion.div variants={item}>
          <ScrapeErrorLog error={scrapeStatus.error} lastRun={scrapeStatus.last_run} />
        </motion.div>
      )}

      {/* Add channel bar */}
      <motion.div variants={item}>
        <GlassCard className="!p-3">
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={channelUrl}
              onChange={(e) => {
                setChannelUrl(e.target.value);
                setAddError("");
              }}
              onKeyDown={(e) => e.key === "Enter" && addChannelMutation.mutate(channelUrl.trim())}
              placeholder="Paste YouTube channel URL (e.g. youtube.com/@ChannelName)"
              className="flex-1 rounded-lg px-4 py-2.5 text-sm font-body outline-none placeholder:opacity-40 transition-all"
              style={{
                background: "var(--bg-elevated)",
                border: `1px solid ${addError ? "var(--red)" : "var(--border)"}`,
                color: "var(--text-primary)",
              }}
              onFocus={(e) => {
                if (!addError) e.target.style.borderColor = "var(--turquoise)";
              }}
              onBlur={(e) => {
                if (!addError) e.target.style.borderColor = "var(--border)";
              }}
            />
            <ActionButton
              onClick={() => addChannelMutation.mutate(channelUrl.trim())}
              disabled={addChannelMutation.isPending || !channelUrl.trim()}
              icon={addChannelMutation.isPending ? undefined : Plus}
            >
              {addChannelMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                "Add"
              )}
            </ActionButton>
            {addError && (
              <span className="text-xs font-body" style={{ color: "var(--red)" }}>
                {addError}
              </span>
            )}
          </div>
        </GlassCard>
      </motion.div>

      {/* Filter + sort bar */}
      <motion.div variants={item} className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Filter size={14} style={{ color: "var(--text-tertiary)" }} />
          <FilterSelect
            options={[
              { value: "all", label: `All Channels (${totalVideos})` },
              ...channelNames.map((name) => ({ value: name, label: name })),
            ]}
            value={channelFilter}
            onChange={handleFilterChange}
          />
        </div>
        <FilterSelect
          options={[
            { value: "vph_desc", label: "Sort: VPH (high)" },
            { value: "vph_asc", label: "Sort: VPH (low)" },
            { value: "views_desc", label: "Sort: Views" },
            { value: "published_desc", label: "Sort: Newest" },
            { value: "scrape_desc", label: "Sort: Recently scraped" },
          ]}
          value={sortBy}
          onChange={handleSortChange}
        />
        <div className="flex-1" />
        <span className="text-xs font-body" style={{ color: "var(--text-tertiary)" }}>
          {totalVideos} video{totalVideos !== 1 ? "s" : ""}
        </span>
      </motion.div>

      {/* Channels strip with delete capability */}
      {channels && channels.length > 0 && (
        <motion.div variants={item} className="flex items-center gap-2 overflow-x-auto pb-1">
          {channels.map((ch) => {
            const displayName = (ch.channel_name && ch.channel_name !== "None")
              ? ch.channel_name
              : ch.channel_url?.match(/@([^/]+)/)?.[1] || `Channel ${ch.id.slice(0, 6)}`;
            const isActive = channelFilter.toLowerCase() === displayName.toLowerCase();
            return (
              <div key={ch.id} className="flex items-center gap-0.5 group">
                <div
                  onClick={() =>
                    setChannelFilter(isActive ? "all" : displayName)
                  }
                  style={{ cursor: "pointer" }}
                  className="flex items-center gap-1.5"
                >
                  <StatusPill
                    label={displayName}
                    color={isActive ? "turquoise" : "gold"}
                    size="md"
                  />
                  {ch.last_scraped && (
                    <span className="text-[9px] font-mono whitespace-nowrap" style={{ color: "var(--text-tertiary)" }}>
                      {timeAgo(ch.last_scraped)}
                    </span>
                  )}
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if (confirm(`Remove "${displayName}" from competitors?`)) {
                      deleteChannelMutation.mutate(ch.id);
                      if (isActive) setChannelFilter("all");
                    }
                  }}
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-red-500/20"
                  title={`Remove ${displayName}`}
                >
                  <X size={12} style={{ color: "var(--text-tertiary)" }} />
                </button>
              </div>
            );
          })}
        </motion.div>
      )}

      {/* Video cards grid */}
      {videos.length > 0 ? (
        <motion.div
          variants={item}
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
        >
          {videos.map((video) => {
            const videoId = video.video_id || video.url?.match(/(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/)?.[1];
            const thumbUrl = video.thumbnail_url || (videoId ? `https://img.youtube.com/vi/${videoId}/hqdefault.jpg` : null);
            return (
              <motion.div
                key={video.id}
                whileHover={{ scale: 1.02, y: -4 }}
                transition={{ type: "spring", stiffness: 300, damping: 25 }}
                className="rounded-xl overflow-hidden cursor-pointer"
                style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
                onClick={() => openModelModal(video)}
              >
                {thumbUrl ? (
                  <img src={thumbUrl} alt={video.title} className="w-full aspect-video object-cover" />
                ) : (
                  <div
                    className="w-full aspect-video flex items-center justify-center"
                    style={{ background: "var(--bg-card-hover)" }}
                  >
                    <span className="text-3xl font-bold" style={{ color: "var(--text-muted)" }}>
                      {video.title?.[0] || "?"}
                    </span>
                  </div>
                )}
                <div className="p-4 space-y-3">
                  <h3 className="text-sm font-semibold leading-tight line-clamp-2" style={{ color: "var(--text-primary)" }}>
                    {video.title}
                  </h3>
                  <div className="flex gap-2 flex-wrap">
                    <div className="px-2.5 py-1 rounded-md text-xs font-bold" style={{ background: "rgba(212, 168, 68, 0.15)", color: "var(--amber)" }}>
                      {formatNumber(video.vph)} VPH
                    </div>
                    <div className="px-2.5 py-1 rounded-md text-xs font-medium" style={{ background: "rgba(26, 138, 122, 0.15)", color: "var(--teal)" }}>
                      {formatNumber(video.views)} views
                    </div>
                    {video.hours_old > 0 && (
                      <div className="px-2.5 py-1 rounded-md text-xs font-medium" style={{ background: "rgba(255,255,255,0.04)", color: "var(--text-secondary)" }}>
                        {Math.round(video.hours_old)}h old
                      </div>
                    )}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs truncate" style={{ color: "var(--text-muted)" }}>
                      {video.channel}
                    </span>
                    {video.duration_seconds != null && (
                      <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                        {Math.floor(video.duration_seconds / 60)}:{String(Math.floor(video.duration_seconds % 60)).padStart(2, "0")}
                      </span>
                    )}
                  </div>
                  <button
                    className="w-full py-2 rounded-lg text-sm font-medium transition-colors"
                    style={{ background: "rgba(212, 168, 68, 0.1)", color: "var(--amber)", border: "1px solid rgba(212, 168, 68, 0.3)" }}
                    onClick={(e) => { e.stopPropagation(); openModelModal(video); }}
                  >
                    Model This &rarr;
                  </button>
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      ) : (
        <motion.div variants={item}>
          <GlassCard className="!p-12 text-center">
            <p className="font-body" style={{ color: "var(--text-tertiary)" }}>
              {channelFilter !== "all"
                ? `No videos from ${channelFilter}`
                : "No competitor videos found. Add channels and scrape to start."}
            </p>
          </GlassCard>
        </motion.div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <motion.div variants={item} className="flex items-center justify-center gap-3">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="p-2 rounded-lg transition-colors disabled:opacity-30"
            style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}
          >
            <ChevronLeft size={16} />
          </button>
          <span className="text-sm font-mono" style={{ color: "var(--text-secondary)" }}>
            {page + 1} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="p-2 rounded-lg transition-colors disabled:opacity-30"
            style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}
          >
            <ChevronRight size={16} />
          </button>
        </motion.div>
      )}

      {/* "Model This" Confirmation Modal */}
      <Modal
        open={modelVideo !== null}
        onClose={() => setModelVideo(null)}
        title="Model Competitor Video"
        size="lg"
      >
        {modelVideo && (
          <div className="space-y-4">
            {/* Source info */}
            <div
              className="rounded-xl p-3 flex items-center gap-3"
              style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
            >
              {(() => {
                const vid = modelVideo.video_id || modelVideo.url?.match(
                  /(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/
                )?.[1];
                const thumb = modelVideo.thumbnail_url || (vid ? `https://img.youtube.com/vi/${vid}/mqdefault.jpg` : null);
                return thumb ? (
                  <img src={thumb} alt="" className="w-24 h-14 rounded-lg object-cover shrink-0" />
                ) : null;
              })()}
              <div className="min-w-0">
                <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>
                  {modelVideo.title}
                </p>
                <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  {modelVideo.channel} &middot; {formatNumber(modelVideo.vph)} VPH &middot;{" "}
                  {formatNumber(modelVideo.views)} views
                </p>
              </div>
            </div>

            {/* Description preview */}
            {modelVideo.description && (
              <div
                className="rounded-lg p-3 text-xs leading-relaxed font-body max-h-32 overflow-y-auto"
                style={{
                  background: "rgba(255,255,255,0.03)",
                  border: "1px solid rgba(255,255,255,0.06)",
                  color: "var(--text-secondary)",
                }}
              >
                {modelVideo.description.slice(0, 500)}
                {modelVideo.description.length > 500 && "..."}
              </div>
            )}

            {/* Form fields */}
            <div>
              <label
                className="block text-[11px] font-medium uppercase tracking-wider mb-1"
                style={{ color: "var(--text-secondary)" }}
              >
                Video Title
              </label>
              <input
                type="text"
                value={modelTitle}
                onChange={(e) => setModelTitle(e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-sm font-body outline-none"
                style={{
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </div>

            <div>
              <label
                className="block text-[11px] font-medium uppercase tracking-wider mb-1"
                style={{ color: "var(--text-secondary)" }}
              >
                Framework Angle (optional)
              </label>
              <input
                type="text"
                value={modelFramework}
                onChange={(e) => setModelFramework(e.target.value)}
                placeholder="e.g. Systems Thinking, Power Doctrine"
                className="w-full rounded-lg px-3 py-2 text-sm font-body outline-none placeholder:opacity-30"
                style={{
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </div>

            <div>
              <label
                className="block text-[11px] font-medium uppercase tracking-wider mb-1"
                style={{ color: "var(--text-secondary)" }}
              >
                Video Length (minutes)
              </label>
              <input
                type="number"
                value={modelLength}
                onChange={(e) => setModelLength(parseInt(e.target.value) || 1)}
                min={1}
                max={60}
                className="w-24 rounded-lg px-3 py-2 text-sm font-body outline-none"
                style={{
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </div>

            {/* Source URL (read-only) */}
            {modelVideo.url && (
              <div>
                <label
                  className="block text-[11px] font-medium uppercase tracking-wider mb-1"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Source URL
                </label>
                <p className="text-xs font-mono truncate" style={{ color: "var(--text-tertiary)" }}>
                  {modelVideo.url}
                </p>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-3 pt-2">
              <button
                onClick={() => setModelVideo(null)}
                className="px-4 py-2.5 rounded-lg text-sm font-medium"
                style={{ color: "var(--text-secondary)", border: "1px solid var(--border)" }}
              >
                Cancel
              </button>
              <ActionButton
                onClick={handleCreateFromVideo}
                disabled={modelCreating || !modelTitle.trim()}
              >
                {modelCreating ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  "Create Video"
                )}
              </ActionButton>
            </div>
          </div>
        )}
      </Modal>
    </motion.div>
  );
}
