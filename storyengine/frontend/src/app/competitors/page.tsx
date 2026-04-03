"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Filter, Plus, Loader2, RefreshCw, X, Trash2, ChevronDown, AlertTriangle, FileText } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import { Modal } from "@/components/ui/modal";
import { NicheSetup } from "@/components/autopilot/niche-setup";
import { PlayingCard } from "@/components/autopilot/playing-card";
import {
  getAutopilotSummary,
  getNicheConfig,
  getNicheChannels,
  addNicheChannel,
  removeNicheChannel,
  createVideo,
  scrapeCompetitorChannels,
  getScrapeStatus,
  getCandidateDetail,
  type CompetitorCandidate,
  type CandidateDetail,
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

type SortOption = "confidence" | "vph" | "freshness";

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
  const [sortBy, setSortBy] = useState<SortOption>("confidence");

  // "Model This" modal state
  const [modelCandidate, setModelCandidate] = useState<CompetitorCandidate | null>(null);
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

  const { data: autopilotData, isLoading } = useQuery({
    queryKey: ["autopilot-summary"],
    queryFn: getAutopilotSummary,
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
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
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

  // Fetch candidate detail (transcript) when model modal is open
  const { data: candidateDetail, isLoading: detailLoading } = useQuery({
    queryKey: ["candidate-detail", modelCandidate?.id],
    queryFn: () => getCandidateDetail(modelCandidate!.id),
    enabled: !!modelCandidate,
  });
  const [transcriptExpanded, setTranscriptExpanded] = useState(false);

  const deleteChannelMutation = useMutation({
    mutationFn: removeNicheChannel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["niche-channels"] });
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
    },
  });

  const scrapeMutation = useMutation({
    mutationFn: scrapeCompetitorChannels,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scrape-status"] });
    },
  });

  const scrapeRunning = scrapeStatus?.is_running ?? false;
  const scrapeFinished = !scrapeRunning && scrapeStatus?.last_run != null;
  const prevRunning = useRef(false);

  // When scrape transitions from running to done, refresh candidates
  useEffect(() => {
    if (prevRunning.current && !scrapeRunning) {
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
    }
    prevRunning.current = scrapeRunning;
  }, [scrapeRunning, queryClient]);

  const nicheConfigured = nicheConfig?.niche_category != null;

  // Unique channel names — merge from candidates + channels table (case-insensitive dedup)
  const channelNames = useMemo(() => {
    const seen = new Map<string, string>(); // lowercase → display name
    // Add source names from candidate data (these are filterable)
    if (autopilotData?.candidates) {
      for (const c of autopilotData.candidates) {
        if (c.source && c.source !== "Unknown") {
          const key = c.source.toLowerCase();
          if (!seen.has(key)) seen.set(key, c.source);
        }
      }
    }
    // Add channel names from channels table (for display completeness)
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
  }, [autopilotData, channels]);

  // Filter + sort candidates
  const filteredCandidates = useMemo(() => {
    if (!autopilotData?.candidates) return [];
    const filterLower = channelFilter.toLowerCase();
    let list =
      channelFilter === "all"
        ? autopilotData.candidates
        : autopilotData.candidates.filter((c) => c.source.toLowerCase() === filterLower);

    switch (sortBy) {
      case "vph":
        list = [...list].sort((a, b) => b.vph - a.vph);
        break;
      case "freshness":
        list = [...list].sort((a, b) => a.hours_old - b.hours_old);
        break;
      case "confidence":
      default:
        list = [...list].sort((a, b) => b.confidence - a.confidence);
        break;
    }
    return list;
  }, [autopilotData, channelFilter, sortBy]);

  const filterOptions = useMemo(
    () => [
      {
        value: "all",
        label: `All Channels (${autopilotData?.candidates?.length || 0})`,
      },
      ...channelNames.map((name) => ({ value: name, label: name })),
    ],
    [autopilotData, channelNames]
  );

  // Open "Model This" modal
  const openModelModal = (candidate: CompetitorCandidate) => {
    setModelCandidate(candidate);
    setModelTitle(candidate.title);
    setModelFramework("");
    setModelLength(10);
    setModelCreating(false);
    setTranscriptExpanded(false);
  };

  // Create video from candidate
  const handleCreateFromCandidate = async () => {
    if (!modelCandidate) return;
    setModelCreating(true);
    try {
      const video = await createVideo({
        title: modelTitle,
        source_url: modelCandidate.url || undefined,
        framework_angle: modelFramework || undefined,
        video_length_minutes: modelLength,
      });
      setModelCandidate(null);
      router.push(`/pipeline/${video.id}`);
    } catch (err) {
      console.error("Failed to create video:", err);
      setModelCreating(false);
    }
  };

  if (!nicheConfigured && nicheConfig) {
    return <NicheSetup onComplete={() => queryClient.invalidateQueries({ queryKey: ["niche-config"] })} />;
  }

  if (isLoading) {
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
      </motion.div>

      {/* Scrape status banner */}
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
          options={[
            { value: "confidence", label: "Sort: Confidence" },
            { value: "vph", label: "Sort: VPH" },
            { value: "freshness", label: "Sort: Freshness" },
          ]}
          value={sortBy}
          onChange={(v) => setSortBy(v as SortOption)}
        />
        <div className="flex-1" />
        <span className="text-xs font-body" style={{ color: "var(--text-tertiary)" }}>
          {filteredCandidates.length} video{filteredCandidates.length !== 1 ? "s" : ""}
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

      {/* Playing cards grid */}
      {filteredCandidates.length > 0 ? (
        <motion.div
          variants={item}
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
        >
          {filteredCandidates.map((candidate) => (
            <PlayingCard
              key={candidate.id}
              candidate={candidate}
              onModel={openModelModal}
            />
          ))}
        </motion.div>
      ) : (
        <motion.div variants={item}>
          <GlassCard className="!p-12 text-center">
            <p className="font-body" style={{ color: "var(--text-tertiary)" }}>
              {channelFilter !== "all"
                ? `No videos from ${channelFilter} above threshold`
                : "No competitor videos found. Add channels to start scanning."}
            </p>
          </GlassCard>
        </motion.div>
      )}

      {/* "Model This" Confirmation Modal */}
      <Modal
        open={modelCandidate !== null}
        onClose={() => setModelCandidate(null)}
        title="Model Competitor Video"
        size="lg"
      >
        {modelCandidate && (
          <div className="space-y-4">
            {/* Source info */}
            <div
              className="rounded-xl p-3 flex items-center gap-3"
              style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
            >
              {(() => {
                const videoId = modelCandidate.url?.match(
                  /(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/
                )?.[1];
                return videoId ? (
                  <img
                    src={`https://img.youtube.com/vi/${videoId}/mqdefault.jpg`}
                    alt=""
                    className="w-24 h-14 rounded-lg object-cover shrink-0"
                  />
                ) : null;
              })()}
              <div className="min-w-0">
                <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>
                  {modelCandidate.title}
                </p>
                <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  {modelCandidate.source} &middot; {formatNumber(modelCandidate.vph)} VPH &middot;{" "}
                  Confidence: {modelCandidate.confidence.toFixed(0)}
                </p>
              </div>
            </div>

            {/* Transcript viewer */}
            {detailLoading ? (
              <div className="flex items-center gap-2 py-2">
                <Loader2 size={14} className="animate-spin" style={{ color: "var(--text-muted)" }} />
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>Loading transcript...</span>
              </div>
            ) : candidateDetail?.transcript ? (
              <div>
                <button
                  onClick={() => setTranscriptExpanded((v) => !v)}
                  className="flex items-center gap-2 w-full text-left"
                >
                  <FileText size={14} style={{ color: "var(--teal)" }} />
                  <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
                    Transcript
                  </span>
                  {candidateDetail.duration_seconds && (
                    <span className="text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>
                      {Math.floor(candidateDetail.duration_seconds / 60)}m {Math.floor(candidateDetail.duration_seconds % 60)}s
                    </span>
                  )}
                  <ChevronDown
                    size={12}
                    className="ml-auto"
                    style={{
                      color: "var(--text-muted)",
                      transform: transcriptExpanded ? "rotate(180deg)" : "rotate(0deg)",
                      transition: "transform 0.2s",
                    }}
                  />
                </button>
                <AnimatePresence>
                  {transcriptExpanded && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="overflow-hidden"
                    >
                      <div
                        className="mt-2 rounded-lg p-3 max-h-64 overflow-y-auto text-xs leading-relaxed font-body"
                        style={{
                          background: "rgba(255,255,255,0.03)",
                          border: "1px solid rgba(255,255,255,0.06)",
                        }}
                      >
                        {(() => {
                          const words = candidateDetail.transcript!.split(/\s+/);
                          const hookWords = words.slice(0, 500).join(" ");
                          const restWords = words.slice(500).join(" ");
                          return (
                            <>
                              <span style={{ color: "var(--text-primary)" }}>{hookWords}</span>
                              {restWords && (
                                <span style={{ color: "var(--text-muted)" }}> {restWords}</span>
                              )}
                            </>
                          );
                        })()}
                      </div>
                      <p className="mt-1 text-[9px]" style={{ color: "var(--text-muted)" }}>
                        First 500 words highlighted as the hook
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            ) : null}

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
            {modelCandidate.url && (
              <div>
                <label
                  className="block text-[11px] font-medium uppercase tracking-wider mb-1"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Source URL
                </label>
                <p className="text-xs font-mono truncate" style={{ color: "var(--text-tertiary)" }}>
                  {modelCandidate.url}
                </p>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-3 pt-2">
              <button
                onClick={() => setModelCandidate(null)}
                className="px-4 py-2.5 rounded-lg text-sm font-medium"
                style={{ color: "var(--text-secondary)", border: "1px solid var(--border)" }}
              >
                Cancel
              </button>
              <ActionButton
                onClick={handleCreateFromCandidate}
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
