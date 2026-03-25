"use client";

import { useState, useEffect, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getAutopilotSummary,
  getNicheConfig,
  getNicheChannels,
  addNicheChannel,
  launchCandidate,
  CompetitorCandidate,
} from "@/lib/api";
import { NicheSetup } from "@/components/autopilot/niche-setup";
import { PlayingCard } from "@/components/autopilot/playing-card";
import { CardExpanded } from "@/components/autopilot/card-expanded";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { ActionButton } from "@/components/ui/ActionButton";
import { AnimatePresence, motion } from "framer-motion";
import { Filter, Plus, Loader2 } from "lucide-react";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

export default function CompetitorsPage() {
  const queryClient = useQueryClient();
  const [selectedCandidate, setSelectedCandidate] = useState<CompetitorCandidate | null>(null);
  const [nicheConfigured, setNicheConfigured] = useState(true);
  const [channelFilter, setChannelFilter] = useState("all");
  const [channelUrl, setChannelUrl] = useState("");
  const [addingChannel, setAddingChannel] = useState(false);
  const [addError, setAddError] = useState("");

  const { data: nicheConfig } = useQuery({
    queryKey: ["niche-config"],
    queryFn: getNicheConfig,
  });

  const { data: channels } = useQuery({
    queryKey: ["niche-channels"],
    queryFn: getNicheChannels,
  });

  const { data: autopilotData, isLoading, refetch } = useQuery({
    queryKey: ["autopilot-summary"],
    queryFn: getAutopilotSummary,
  });

  useEffect(() => {
    if (nicheConfig && !nicheConfig.niche_category) {
      setNicheConfigured(false);
    } else if (nicheConfig) {
      setNicheConfigured(true);
    }
  }, [nicheConfig]);

  // Get unique channel names from candidates
  const channelNames = useMemo(() => {
    if (!autopilotData?.candidates) return [];
    const names = new Set(autopilotData.candidates.map((c) => c.source));
    return Array.from(names).sort();
  }, [autopilotData]);

  const handleAddChannel = async () => {
    const url = channelUrl.trim();
    if (!url) return;
    setAddError("");
    setAddingChannel(true);
    try {
      // Extract channel name from URL: @Handle or /c/Name or /channel/ID
      const match = url.match(/@([^/?]+)/)?.[1]
        || url.match(/\/c\/([^/?]+)/)?.[1]
        || url.match(/\/channel\/([^/?]+)/)?.[1];
      const name = match || new URL(url).pathname.split("/").filter(Boolean).pop() || "Unknown";
      await addNicheChannel(name, url);
      setChannelUrl("");
      queryClient.invalidateQueries({ queryKey: ["niche-channels"] });
      queryClient.invalidateQueries({ queryKey: ["autopilot-summary"] });
    } catch (err: any) {
      setAddError(err.message || "Failed to add channel");
    } finally {
      setAddingChannel(false);
    }
  };

  // Filter candidates by channel
  const filteredCandidates = useMemo(() => {
    if (!autopilotData?.candidates) return [];
    if (channelFilter === "all") return autopilotData.candidates;
    return autopilotData.candidates.filter((c) => c.source === channelFilter);
  }, [autopilotData, channelFilter]);

  const filterOptions = useMemo(() => [
    { value: "all", label: `All Channels (${autopilotData?.candidates?.length || 0})` },
    ...channelNames.map((name) => ({ value: name, label: name })),
  ], [autopilotData, channelNames]);

  if (!nicheConfigured) {
    return <NicheSetup onComplete={() => setNicheConfigured(true)} />;
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 rounded animate-pulse" style={{ background: "var(--border)" }} />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-72 rounded-xl animate-pulse glass-card" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <motion.div
      className="space-y-6"
      variants={container}
      initial="hidden"
      animate="show"
    >
      {/* Header */}
      <motion.div variants={item} className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display" style={{ color: "var(--text-primary)" }}>
            Competitor Analysis
          </h1>
          {nicheConfig?.sub_niche && (
            <p className="text-sm mt-1 font-body" style={{ color: "var(--text-secondary)" }}>
              {nicheConfig.niche_category} · {nicheConfig.sub_niche}
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
              onChange={(e) => { setChannelUrl(e.target.value); setAddError(""); }}
              onKeyDown={(e) => e.key === "Enter" && handleAddChannel()}
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
              onClick={handleAddChannel}
              disabled={addingChannel || !channelUrl.trim()}
              icon={addingChannel ? undefined : Plus}
            >
              {addingChannel ? <Loader2 size={14} className="animate-spin" /> : "Add"}
            </ActionButton>
            {addError && (
              <span className="text-xs font-body" style={{ color: "var(--red)" }}>{addError}</span>
            )}
          </div>
        </GlassCard>
      </motion.div>

      {/* Filter bar */}
      <motion.div variants={item} className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Filter size={14} style={{ color: "var(--text-muted)" }} />
          <FilterSelect
            options={filterOptions}
            value={channelFilter}
            onChange={setChannelFilter}
          />
        </div>

        <div className="flex-1" />

        <span className="text-xs font-body" style={{ color: "var(--text-muted)" }}>
          {filteredCandidates.length} video{filteredCandidates.length !== 1 ? "s" : ""}
        </span>
      </motion.div>

      {/* Channels strip */}
      {channels && channels.length > 0 && (
        <motion.div variants={item} className="flex items-center gap-2 overflow-x-auto pb-1">
          {channels.map((ch: any) => (
            <div
              key={ch.id}
              onClick={() => setChannelFilter(channelFilter === ch.channel_name ? "all" : ch.channel_name)}
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
        <motion.div variants={item} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredCandidates.map((candidate) => (
            <PlayingCard
              key={candidate.id}
              candidate={candidate}
              onModel={setSelectedCandidate}
            />
          ))}
        </motion.div>
      ) : (
        <motion.div variants={item}>
          <GlassCard className="!p-12 text-center">
            <p className="font-body" style={{ color: "var(--text-muted)" }}>
              {channelFilter !== "all"
                ? `No videos from ${channelFilter} above threshold`
                : "No competitor videos found. Add channels to start scanning."}
            </p>
          </GlassCard>
        </motion.div>
      )}

      {/* Expanded card modal */}
      <AnimatePresence>
        {selectedCandidate && (
          <CardExpanded
            candidate={selectedCandidate}
            onClose={() => setSelectedCandidate(null)}
            onProduce={async (candidate) => {
              try {
                await launchCandidate(candidate.id);
                setSelectedCandidate(null);
                refetch();
              } catch (err) {
                console.error("Failed to launch:", err);
              }
            }}
          />
        )}
      </AnimatePresence>
    </motion.div>
  );
}
