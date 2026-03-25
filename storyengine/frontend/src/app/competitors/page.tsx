"use client";

import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getAutopilotSummary,
  getNicheConfig,
  getNicheChannels,
  launchCandidate,
  CompetitorCandidate,
} from "@/lib/api";
import { NicheSetup } from "@/components/autopilot/niche-setup";
import { PlayingCard } from "@/components/autopilot/playing-card";
import { CardExpanded } from "@/components/autopilot/card-expanded";
import { AnimatePresence } from "framer-motion";
import { Filter } from "lucide-react";

export default function CompetitorsPage() {
  const [selectedCandidate, setSelectedCandidate] = useState<CompetitorCandidate | null>(null);
  const [nicheConfigured, setNicheConfigured] = useState(true);
  const [channelFilter, setChannelFilter] = useState("all");

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

  // Filter candidates by channel
  const filteredCandidates = useMemo(() => {
    if (!autopilotData?.candidates) return [];
    if (channelFilter === "all") return autopilotData.candidates;
    return autopilotData.candidates.filter((c) => c.source === channelFilter);
  }, [autopilotData, channelFilter]);

  if (!nicheConfigured) {
    return <NicheSetup onComplete={() => setNicheConfigured(true)} />;
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 rounded animate-pulse" style={{ background: "var(--border)" }} />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-72 rounded-xl animate-pulse" style={{ background: "var(--bg-card)" }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
            Competitor Analysis
          </h1>
          {nicheConfig?.sub_niche && (
            <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
              {nicheConfig.niche_category} · {nicheConfig.sub_niche}
            </p>
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Filter size={14} style={{ color: "var(--text-muted)" }} />
          <select
            value={channelFilter}
            onChange={(e) => setChannelFilter(e.target.value)}
            className="rounded-lg px-3 py-2 text-sm outline-none"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          >
            <option value="all">All Channels ({autopilotData?.candidates?.length || 0})</option>
            {channelNames.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>

        <div className="flex-1" />

        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          {filteredCandidates.length} video{filteredCandidates.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Channels strip */}
      {channels && channels.length > 0 && (
        <div className="flex items-center gap-2 overflow-x-auto pb-1">
          {channels.map((ch: any) => (
            <div
              key={ch.id}
              className="flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium shrink-0"
              style={{
                background: channelFilter === ch.channel_name ? "rgba(212, 168, 68, 0.15)" : "var(--bg-card)",
                color: channelFilter === ch.channel_name ? "var(--amber)" : "var(--text-secondary)",
                border: `1px solid ${channelFilter === ch.channel_name ? "rgba(212, 168, 68, 0.3)" : "var(--border)"}`,
                cursor: "pointer",
              }}
              onClick={() => setChannelFilter(channelFilter === ch.channel_name ? "all" : ch.channel_name)}
            >
              {ch.channel_name}
            </div>
          ))}
        </div>
      )}

      {/* Playing cards grid */}
      {filteredCandidates.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredCandidates.map((candidate) => (
            <PlayingCard
              key={candidate.id}
              candidate={candidate}
              onModel={setSelectedCandidate}
            />
          ))}
        </div>
      ) : (
        <div
          className="rounded-xl p-12 text-center"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <p style={{ color: "var(--text-muted)" }}>
            {channelFilter !== "all"
              ? `No videos from ${channelFilter} above threshold`
              : "No competitor videos found. Add channels to start scanning."}
          </p>
        </div>
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
    </div>
  );
}
