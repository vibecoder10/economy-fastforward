"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { X } from "lucide-react";
import { ThumbnailWorkshop, ThumbnailVersion } from "./thumbnail-workshop";
import { formatNumber } from "@/lib/utils";
import type { CompetitorCandidate, CandidateIntelligence } from "@/lib/api";

interface CardExpandedProps {
  candidate: CompetitorCandidate;
  onClose: () => void;
  onProduce: (candidate: CompetitorCandidate, thumbnailVersion: ThumbnailVersion | null) => void;
}

export function CardExpanded({ candidate, onClose, onProduce }: CardExpandedProps) {
  const [versions, setVersions] = useState<ThumbnailVersion[]>([]);
  const [lockedVersion, setLockedVersion] = useState<ThumbnailVersion | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [intelligence, setIntelligence] = useState<CandidateIntelligence | null>(null);

  // Fetch intelligence data for this candidate
  useEffect(() => {
    const fetchIntel = async () => {
      try {
        const { getCandidateDetail } = await import("@/lib/api");
        const detail = await getCandidateDetail(candidate.id);
        if (detail.intelligence) setIntelligence(detail.intelligence);
      } catch {}
    };
    fetchIntel();
  }, [candidate.id]);

  const videoId = candidate.url?.match(/(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/)?.[1];
  const theirThumbnail = videoId
    ? `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`
    : null;

  // Initial thumbnail prompt based on competitor
  const initialPrompt = `Bold editorial illustration, dramatic lighting. Topic: "${candidate.title}". High contrast, large text overlay, attention-grabbing composition. 16:9 aspect ratio.`;

  const handleGenerate = async (prompt: string) => {
    setIsGenerating(true);
    // For now, add version with no image (backend thumbnail generation not wired yet)
    // When wired: call POST /api/thumbnails/generate with prompt
    const newVersion: ThumbnailVersion = {
      prompt,
      imageUrl: null, // Will be populated when backend thumbnail endpoint exists
    };
    setVersions((prev) => [...prev, newVersion]);
    setIsGenerating(false);
  };

  const handleLock = (version: ThumbnailVersion) => {
    setLockedVersion(version);
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.8)" }}
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.9, opacity: 0 }}
        className="rounded-xl overflow-hidden w-full max-w-3xl max-h-[90vh] overflow-y-auto"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between p-4"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            Model Competitor Video
          </h2>
          <button onClick={onClose} style={{ color: "var(--text-muted)" }}>
            <X size={20} />
          </button>
        </div>

        {/* Side by side */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-0">
          {/* THEIRS */}
          <div className="p-4" style={{ borderRight: "1px solid var(--border)" }}>
            <h3
              className="text-xs font-semibold uppercase tracking-wider mb-3"
              style={{ color: "var(--text-muted)" }}
            >
              Theirs
            </h3>
            {theirThumbnail && (
              <img
                src={theirThumbnail}
                alt={candidate.title}
                className="w-full rounded-lg aspect-video object-cover mb-3"
              />
            )}
            <p className="text-sm font-medium mb-3" style={{ color: "var(--text-primary)" }}>
              {candidate.title}
            </p>
            <div className="space-y-1 text-xs" style={{ color: "var(--text-secondary)" }}>
              <p>VPH: <span className="font-bold" style={{ color: "var(--amber)" }}>{formatNumber(candidate.vph)}</span></p>
              <p>Channel: {candidate.source}</p>
              <p>Age: {Math.round(candidate.hours_old)}h</p>
              <p>Confidence: {candidate.confidence.toFixed(0)}/100</p>
            </div>

            {/* Intelligence DNA */}
            {intelligence && (
              <div className="mt-4 space-y-2">
                <h4 className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--amber)" }}>
                  Why It Works
                </h4>
                {intelligence.summary && (
                  <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                    {intelligence.summary}
                  </p>
                )}
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {intelligence.metadata.hook_dna?.type && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: "rgba(251,191,36,0.15)", color: "var(--amber)" }}>
                      Hook: {intelligence.metadata.hook_dna.type}
                    </span>
                  )}
                  {intelligence.metadata.content_dna?.tone && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: "rgba(59,130,246,0.15)", color: "#60a5fa" }}>
                      Tone: {intelligence.metadata.content_dna.tone}
                    </span>
                  )}
                  {intelligence.metadata.title_dna?.structure && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: "rgba(168,85,247,0.15)", color: "#c084fc" }}>
                      Title: {intelligence.metadata.title_dna.structure}
                    </span>
                  )}
                  {intelligence.metadata.thumbnail_dna?.overall_style && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: "rgba(34,197,94,0.15)", color: "#4ade80" }}>
                      Thumb: {intelligence.metadata.thumbnail_dna.overall_style}
                    </span>
                  )}
                  {intelligence.metadata.thumbnail_dna?.face_emotion && intelligence.metadata.thumbnail_dna.face_emotion !== "none" && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: "rgba(244,63,94,0.15)", color: "#fb7185" }}>
                      Face: {intelligence.metadata.thumbnail_dna.face_emotion}
                    </span>
                  )}
                  {intelligence.metadata.engagement_signals?.controversy_level && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: "rgba(251,146,60,0.15)", color: "#fb923c" }}>
                      Controversy: {intelligence.metadata.engagement_signals.controversy_level}
                    </span>
                  )}
                </div>
                {intelligence.metadata.content_dna?.topic_tags && intelligence.metadata.content_dna.topic_tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {intelligence.metadata.content_dna.topic_tags.slice(0, 5).map((tag) => (
                      <span key={tag} className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: "rgba(255,255,255,0.06)", color: "var(--text-muted)" }}>
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
                {intelligence.metadata.hook_dna?.opening_line && (
                  <p className="text-[10px] italic mt-1" style={{ color: "var(--text-muted)" }}>
                    &ldquo;{intelligence.metadata.hook_dna.opening_line}&rdquo;
                  </p>
                )}
              </div>
            )}
          </div>

          {/* YOURS */}
          <div className="p-4">
            <h3
              className="text-xs font-semibold uppercase tracking-wider mb-3"
              style={{ color: "var(--amber)" }}
            >
              Yours
            </h3>
            {lockedVersion?.imageUrl ? (
              <img
                src={lockedVersion.imageUrl}
                alt="Your version"
                className="w-full rounded-lg aspect-video object-cover mb-3"
              />
            ) : (
              <div
                className="w-full rounded-lg aspect-video flex items-center justify-center mb-3"
                style={{ background: "var(--bg-card-hover)", border: "2px dashed var(--border)" }}
              >
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  Generate below
                </span>
              </div>
            )}
            <p className="text-sm mb-2" style={{ color: "var(--text-secondary)" }}>
              Your version will use data-driven patterns to outperform.
            </p>
            {candidate.confidence_breakdown && (
              <div className="space-y-1 text-xs" style={{ color: "var(--text-muted)" }}>
                <p>{candidate.confidence_breakdown.vph_reasoning}</p>
                <p>{candidate.confidence_breakdown.freshness_reasoning}</p>
                {candidate.confidence_breakdown.intelligence_reasoning && candidate.confidence_breakdown.intelligence_score > 0 && (
                  <p style={{ color: "var(--amber)" }}>{candidate.confidence_breakdown.intelligence_reasoning}</p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Thumbnail Workshop */}
        <div className="p-4" style={{ borderTop: "1px solid var(--border)" }}>
          <ThumbnailWorkshop
            initialPrompt={initialPrompt}
            versions={versions}
            onGenerate={handleGenerate}
            onLock={handleLock}
            isGenerating={isGenerating}
          />
        </div>

        {/* Footer actions */}
        <div
          className="flex gap-3 p-4"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <button
            onClick={onClose}
            className="px-4 py-2.5 rounded-lg text-sm font-medium"
            style={{ color: "var(--text-secondary)", border: "1px solid var(--border)" }}
          >
            Cancel
          </button>
          <button
            onClick={() => onProduce(candidate, lockedVersion)}
            className="flex-1 py-2.5 rounded-lg text-sm font-semibold"
            style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
          >
            {lockedVersion ? "Lock & Produce \u2192" : "Produce \u2192"}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
