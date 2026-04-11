"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { formatNumber } from "@/lib/utils";
import type { CompetitorCandidate } from "@/lib/api";

interface PlayingCardProps {
  candidate: CompetitorCandidate;
  onModel: (candidate: CompetitorCandidate) => void;
}

export function PlayingCard({ candidate, onModel }: PlayingCardProps) {
  const [showBreakdown, setShowBreakdown] = useState(false);
  const breakdown = candidate.confidence_breakdown;
  // Build YouTube thumbnail URL from video URL
  const videoId = candidate.url?.match(/(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/)?.[1];
  const thumbnailUrl = videoId
    ? `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`
    : null;

  return (
    <motion.div
      whileHover={{ scale: 1.02, y: -4 }}
      transition={{ type: "spring", stiffness: 300, damping: 25 }}
      className="rounded-xl overflow-hidden cursor-pointer"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
      }}
      onClick={() => onModel(candidate)}
    >
      {/* Thumbnail */}
      {thumbnailUrl ? (
        <img
          src={thumbnailUrl}
          alt={candidate.title}
          className="w-full aspect-video object-cover"
        />
      ) : (
        <div
          className="w-full aspect-video flex items-center justify-center"
          style={{ background: "var(--bg-card-hover)" }}
        >
          <span className="text-3xl font-bold" style={{ color: "var(--text-muted)" }}>
            {candidate.title?.[0] || "?"}
          </span>
        </div>
      )}

      {/* Content */}
      <div className="p-4 space-y-3">
        {/* Title */}
        <h3
          className="text-sm font-semibold leading-tight line-clamp-2"
          style={{ color: "var(--text-primary)" }}
        >
          {candidate.title}
        </h3>

        {/* Stats row */}
        <div className="flex gap-2">
          <div
            className="px-2.5 py-1 rounded-md text-xs font-bold"
            style={{ background: "rgba(212, 168, 68, 0.15)", color: "var(--amber)" }}
          >
            {formatNumber(candidate.vph)} VPH
          </div>
          <div
            className="px-2.5 py-1 rounded-md text-xs font-medium"
            style={{ background: "rgba(26, 138, 122, 0.15)", color: "var(--teal)" }}
          >
            {Math.round(candidate.hours_old)}h fresh
          </div>
        </div>

        {/* Channel + confidence */}
        <div className="flex items-center justify-between">
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {candidate.source}
          </span>
          <button
            className="flex items-center gap-2"
            onClick={(e) => {
              e.stopPropagation();
              if (breakdown) setShowBreakdown((v) => !v);
            }}
            style={{ cursor: breakdown ? "pointer" : "default" }}
          >
            <div
              className="h-1.5 w-16 rounded-full overflow-hidden"
              style={{ background: "var(--bg-card-hover)" }}
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.min(100, candidate.confidence)}%`,
                  background: "var(--amber)",
                }}
              />
            </div>
            <span className="text-xs font-bold" style={{ color: "var(--amber)" }}>
              {candidate.confidence.toFixed(0)}
            </span>
            {breakdown && (
              <ChevronDown
                size={12}
                style={{
                  color: "var(--text-muted)",
                  transform: showBreakdown ? "rotate(180deg)" : "rotate(0deg)",
                  transition: "transform 0.2s",
                }}
              />
            )}
          </button>
        </div>

        {/* Confidence breakdown */}
        <AnimatePresence>
          {showBreakdown && breakdown && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div
                className="rounded-lg p-3 space-y-2"
                style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
              >
                {[
                  { label: "VPH Score", score: breakdown.vph_score, reasoning: breakdown.vph_reasoning },
                  { label: "Freshness", score: breakdown.freshness_score, reasoning: breakdown.freshness_reasoning },
                  ...(breakdown.intelligence_score > 0
                    ? [{ label: "Intelligence", score: breakdown.intelligence_score, reasoning: breakdown.intelligence_reasoning }]
                    : []),
                ].map((item) => (
                  <div key={item.label}>
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-[10px] font-medium" style={{ color: "var(--text-secondary)" }}>
                        {item.label}
                      </span>
                      <span className="text-[10px] font-mono font-bold" style={{ color: "var(--amber)" }}>
                        {item.score.toFixed(1)}
                      </span>
                    </div>
                    <div
                      className="h-1 rounded-full overflow-hidden mb-1"
                      style={{ background: "rgba(255,255,255,0.06)" }}
                    >
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${Math.min(100, item.score)}%`, background: "var(--amber)" }}
                      />
                    </div>
                    {item.reasoning && (
                      <p className="text-[9px] leading-tight" style={{ color: "var(--text-muted)" }}>
                        {item.reasoning}
                      </p>
                    )}
                  </div>
                ))}
                <div className="flex items-center justify-between pt-1" style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
                  <span className="text-[10px] font-semibold" style={{ color: "var(--text-secondary)" }}>
                    Total
                  </span>
                  <span className="text-[10px] font-mono font-bold" style={{ color: "var(--amber)" }}>
                    {breakdown.total_score.toFixed(1)}
                  </span>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Model button */}
        <button
          className="w-full py-2 rounded-lg text-sm font-medium transition-colors"
          style={{
            background: "rgba(212, 168, 68, 0.1)",
            color: "var(--amber)",
            border: "1px solid rgba(212, 168, 68, 0.3)",
          }}
          onClick={(e) => {
            e.stopPropagation();
            onModel(candidate);
          }}
        >
          Model This &rarr;
        </button>
      </div>
    </motion.div>
  );
}
