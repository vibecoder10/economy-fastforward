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
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorCard } from "@/components/ui/ErrorCard";
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
  searchIntelligence,
  type NicheVideo,
  type IntelligenceSearchResult,
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

const SORT_OPTIONS = [
  { value: "vph_desc", label: "Sort: VPH (high)" },
  { value: "vph_asc", label: "Sort: VPH (low)" },
  { value: "views_desc", label: "Sort: Views" },
  { value: "published_desc", label: "Sort: Newest" },
  { value: "scrape_desc", label: "Sort: Recently Scraped" },
];

function ScrapeErrorLog({ error, lastRun }: { error: string; lastRun: string | null }) {
  const [expanded, setExpanded] = useState(false);
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

  // Semantic search
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<IntelligenceSearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);

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

  // Server-side paginated + filtered + sorted videos
  const { data: videosData, isLoading } = useQuery({
    queryKey: ["niche-videos", channelFilter, sortBy, page],
    queryFn: () =>
      getNicheVideos({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        channel: channelFilter !== "all" ? channelFilter : undefined,
        sort: sortBy,
      }),
  });

  const videos = videosData?.videos ?? [];
  const totalVideos = videosData?.total ?? 0;
  const serverChannels = videosData?.channels ?? [];
  const totalPages = Math.ceil(totalVideos / PAGE_SIZE);

  // Reset page when filter/sort changes
  useEffect(() => {
    setPage(0);
  }, [channelFilter, sortBy]);

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

  // Build channel filter options from server response + channels table
  const channelNames = (() => {
    const seen = new Map<string, string>();
    for (const name of serverChannels) {
      if (name && name !== "Unknown") {
        const key = name.toLowerCase();
        if (!seen.has(key)) seen.set(key, name);
      }
    }
    if (channels) {
      for (const ch of channels) {
        const displayName = (ch.channel_name && ch.channel_name !== "None")
          ? ch.channel_name
          : ch.channel_url?.match(/@([^/]+)/)?.[1];
        if (displayName) {
          const key = displayName.toLowerCase();
          if (!seen.has(key)) seen.set(key, displayName);
        }
      }
    }
    return Array.from(seen.values()).sort();
  })();

  const filterOptions = [
    { value: "all", label: `All Channels (${totalVideos})` },
    ...channelNames.map((name) => ({ value: name, label: name })),
  ];

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
      const created = await createVideo({
        title: modelTitle,
        source_url: modelVideo.url || undefined,
        framework_angle: modelFramework || undefined,
        video_length_minutes: modelLength,
      });
      setModelVideo(null);
      router.push(`/pipeline/${created.id}`);
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
            <ActionButton
              icon={StopCircle}
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
            >
              Cancel
            </ActionButton>
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

      {/* Per-channel scrape progress */}
      {scrapeRunning && scrapeStatus && scrapeStatus.channels_total > 0 && (
        <motion.div variants={item}>
          <GlassCard className="!p-4 space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span style={{ color: "var(--text-secondary)" }}>
                Scraping: {scrapeStatus.current_channel || "..."} ({scrapeStatus.channels_done}/{scrapeStatus.channels_total} channels)
              </span>
              <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                {scrapeStatus.videos_found} found · {scrapeStatus.videos_saved} saved
              </span>
            </div>
            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-elevated)" }}>
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  background: "var(--turquoise)",
                  width: `${scrapeStatus.channels_total > 0 ? (scrapeStatus.channels_done / scrapeStatus.channels_total) * 100 : 0}%`,
                }}
              />
            </div>
            {scrapeStatus.channel_progress && Object.keys(scrapeStatus.channel_progress).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(scrapeStatus.channel_progress).map(([ch, count]) => (
                  <span
                    key={ch}
                    className="text-[10px] px-2 py-0.5 rounded-full font-mono"
                    style={{
                      background: ch === scrapeStatus.current_channel
                        ? "rgba(0, 212, 170, 0.15)"
                        : "rgba(255,255,255,0.04)",
                      color: ch === scrapeStatus.current_channel
                        ? "var(--turquoise)"
                        : "var(--text-tertiary)",
                      border: `1px solid ${ch === scrapeStatus.current_channel ? "rgba(0, 212, 170, 0.3)" : "rgba(255,255,255,0.06)"}`,
                    }}
                  >
                    {ch}: {count}
                  </span>
                ))}
              </div>
            )}
          </GlassCard>
        </motion.div>
      )}

      {/* Scrape completed banner */}
      {scrapeFinished && !scrapeStatus?.error && scrapeStatus?.videos_found != null && !scrapeRunning && (
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
      {scrapeStatus?.error && (
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
          <FilterSelect options={filterOptions} value={channelFilter} onChange={setChannelFilter} />
        </div>
        <FilterSelect
          options={SORT_OPTIONS}
          value={sortBy}
          onChange={(v) => setSortBy(v as SortOption)}
        />
        <div className="flex-1" />
        <span className="text-xs font-body" style={{ color: "var(--text-tertiary)" }}>
          {totalVideos} video{totalVideos !== 1 ? "s" : ""}
          {totalPages > 1 && ` · Page ${page + 1}/${totalPages}`}
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
                    if (confirm(`Remove "${displayName}" and all its videos?`)) {
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

      {/* Semantic search */}
      <motion.div variants={item}>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={async (e) => {
              if (e.key === "Enter" && searchQuery.trim().length >= 2) {
                setSearching(true);
                try {
                  const res = await searchIntelligence(searchQuery.trim(), 12);
                  setSearchResults(res.results);
                } catch {
                  setSearchResults([]);
                } finally {
                  setSearching(false);
                }
              }
            }}
            placeholder="Search competitor intelligence... (e.g. &quot;AI regulation&quot;, &quot;viral hooks&quot;)"
            className="flex-1 rounded-lg px-4 py-2 text-sm font-body outline-none placeholder:opacity-40"
            style={{
              background: "var(--bg-elevated)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
          {searching && <Loader2 size={16} className="animate-spin" style={{ color: "var(--amber)" }} />}
          {searchResults && (
            <button
              onClick={() => { setSearchResults(null); setSearchQuery(""); }}
              className="text-xs px-2 py-1 rounded"
              style={{ color: "var(--text-muted)" }}
            >
              Clear
            </button>
          )}
        </div>
      </motion.div>

      {/* Search results */}
      {searchResults && (
        <motion.div variants={item} className="space-y-2">
          <p className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
            {searchResults.length} results for &ldquo;{searchQuery}&rdquo;
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {searchResults.map((r) => (
              <GlassCard key={r.id} className="!p-3 space-y-2">
                <div className="flex items-center gap-2">
                  {r.source_thumbnail_url && (
                    <img src={r.source_thumbnail_url} alt="" className="w-16 h-10 rounded object-cover shrink-0" />
                  )}
                  <div className="min-w-0">
                    <p className="text-xs font-medium line-clamp-2" style={{ color: "var(--text-primary)" }}>
                      {r.source_title || "Untitled"}
                    </p>
                    <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>{r.source_channel}</p>
                  </div>
                </div>
                <p className="text-[11px] line-clamp-2" style={{ color: "var(--text-secondary)" }}>{r.summary}</p>
                <div className="flex items-center gap-2">
                  {r.similarity != null && (
                    <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-full" style={{ background: "rgba(251,191,36,0.12)", color: "var(--amber)" }}>
                      {(r.similarity * 100).toFixed(0)}% match
                    </span>
                  )}
                  {r.source_vph != null && (
                    <span className="text-[9px] font-mono" style={{ color: "var(--turquoise)" }}>
                      {formatNumber(r.source_vph)} VPH
                    </span>
                  )}
                </div>
              </GlassCard>
            ))}
          </div>
        </motion.div>
      )}

      {/* Video cards grid */}
      {videos.length > 0 ? (
        <motion.div
          variants={item}
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
        >
          {videos.map((video) => {
            const thumbUrl = video.thumbnail_url
              || (video.video_id ? `https://img.youtube.com/vi/${video.video_id}/mqdefault.jpg` : null);
            return (
              <GlassCard key={video.id} className="!p-0 overflow-hidden group">
                {thumbUrl && (
                  <div className="relative aspect-video overflow-hidden">
                    <img
                      src={thumbUrl}
                      alt=""
                      className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                    />
                    <div
                      className="absolute bottom-2 right-2 text-[10px] font-mono px-1.5 py-0.5 rounded"
                      style={{ background: "rgba(0,0,0,0.7)", color: "#fff" }}
                    >
                      {formatNumber(video.vph)} VPH
                    </div>
                  </div>
                )}
                <div className="p-3 space-y-2">
                  <p
                    className="text-sm font-medium leading-tight line-clamp-2"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {video.title}
                  </p>
                  <div className="flex items-center gap-2 text-[11px]" style={{ color: "var(--text-secondary)" }}>
                    <span>{video.channel}</span>
                    <span style={{ color: "var(--text-tertiary)" }}>&middot;</span>
                    <span>{formatNumber(video.views)} views</span>
                    {video.hours_old != null && (
                      <>
                        <span style={{ color: "var(--text-tertiary)" }}>&middot;</span>
                        <span>{video.hours_old < 24 ? `${Math.round(video.hours_old)}h` : `${Math.round(video.hours_old / 24)}d`} old</span>
                      </>
                    )}
                  </div>
                  {/* DNA badges from distilled intelligence */}
                  {video.has_dna && (
                    <div className="flex flex-wrap gap-1">
                      {video.hook_type && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: "rgba(251,191,36,0.12)", color: "var(--amber)" }}>
                          {video.hook_type}
                        </span>
                      )}
                      {video.tone && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: "rgba(59,130,246,0.12)", color: "#60a5fa" }}>
                          {video.tone}
                        </span>
                      )}
                      {video.thumbnail_style && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: "rgba(34,197,94,0.12)", color: "#4ade80" }}>
                          {video.thumbnail_style}
                        </span>
                      )}
                      {video.face_emotion && video.face_emotion !== "none" && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: "rgba(244,63,94,0.12)", color: "#fb7185" }}>
                          {video.face_emotion}
                        </span>
                      )}
                      {video.views_per_sub_ratio != null && video.views_per_sub_ratio > 1.0 && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: "rgba(168,85,247,0.12)", color: "#c084fc" }}>
                          {video.views_per_sub_ratio.toFixed(1)}x viral
                        </span>
                      )}
                    </div>
                  )}
                  <div className="flex items-center justify-between pt-1">
                    <div className="flex items-center gap-2">
                      <StatusPill
                        label={`${formatNumber(video.vph)} VPH`}
                        color={video.vph >= 100 ? "turquoise" : video.vph >= 30 ? "gold" : "slate"}
                        size="sm"
                      />
                      {video.likes != null && video.likes > 0 && (
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          {formatNumber(video.likes)} likes
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => openModelModal(video)}
                      className="text-[11px] px-3 py-1.5 rounded-lg font-medium transition-opacity hover:opacity-80"
                      style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
                    >
                      Model This
                    </button>
                  </div>
                </div>
              </GlassCard>
            );
          })}
        </motion.div>
      ) : (
        <motion.div variants={item}>
          <EmptyState
            icon={Filter}
            title={channelFilter !== "all" ? `No videos from ${channelFilter}` : "No competitor videos found"}
            description={channelFilter !== "all" ? "Try a different channel filter." : "Add channels and scrape to start."}
          />
        </motion.div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <motion.div variants={item} className="flex items-center justify-center gap-3">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="flex items-center gap-1 text-sm px-3 py-2 rounded-lg font-medium transition-opacity disabled:opacity-30"
            style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
          >
            <ChevronLeft size={14} /> Prev
          </button>
          <span className="text-sm font-mono" style={{ color: "var(--text-tertiary)" }}>
            {page + 1} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="flex items-center gap-1 text-sm px-3 py-2 rounded-lg font-medium transition-opacity disabled:opacity-30"
            style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
          >
            Next <ChevronRight size={14} />
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
            <div
              className="rounded-xl p-3 flex items-center gap-3"
              style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
            >
              {(() => {
                const thumbUrl = modelVideo.thumbnail_url
                  || (modelVideo.video_id ? `https://img.youtube.com/vi/${modelVideo.video_id}/mqdefault.jpg` : null);
                return thumbUrl ? (
                  <img
                    src={thumbUrl}
                    alt=""
                    className="w-24 h-14 rounded-lg object-cover shrink-0"
                  />
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
