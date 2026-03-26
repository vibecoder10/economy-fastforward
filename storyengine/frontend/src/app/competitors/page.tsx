"use client";

import { useState, useMemo } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Filter, Plus, Loader2 } from "lucide-react";
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
  createVideo,
  type CompetitorCandidate,
} from "@/lib/api";
import { formatNumber } from "@/lib/utils";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

type SortOption = "confidence" | "vph" | "freshness";

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

  const nicheConfigured = nicheConfig?.niche_category != null;

  // Unique channel names from candidates
  const channelNames = useMemo(() => {
    if (!autopilotData?.candidates) return [];
    const names = new Set(autopilotData.candidates.map((c) => c.source));
    return Array.from(names).sort();
  }, [autopilotData]);

  // Filter + sort candidates
  const filteredCandidates = useMemo(() => {
    if (!autopilotData?.candidates) return [];
    let list =
      channelFilter === "all"
        ? autopilotData.candidates
        : autopilotData.candidates.filter((c) => c.source === channelFilter);

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
      </motion.div>

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

      {/* Channels strip */}
      {channels && channels.length > 0 && (
        <motion.div variants={item} className="flex items-center gap-2 overflow-x-auto pb-1">
          {channels.map((ch) => (
            <div
              key={ch.id}
              onClick={() =>
                setChannelFilter(channelFilter === ch.channel_name ? "all" : ch.channel_name)
              }
              style={{ cursor: "pointer" }}
            >
              <StatusPill
                label={ch.channel_name}
                color={channelFilter === ch.channel_name ? "turquoise" : "gold"}
                size="md"
              />
            </div>
          ))}
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
