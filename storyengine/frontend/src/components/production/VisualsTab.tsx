"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Check, Loader2, Image as ImageIcon } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { MOCK_IMAGE_GEN_ITEMS } from "@/lib/mock-data";
import type { Video } from "@/lib/types";

interface VisualsTabProps {
  video: Video;
}

export function VisualsTab({ video }: VisualsTabProps) {
  const [model, setModel] = useState("nano-banana-2");
  const [styleProfile, setStyleProfile] = useState("holographic-hud");

  const completedCount = MOCK_IMAGE_GEN_ITEMS.filter((i) => i.completed).length;
  const totalCount = MOCK_IMAGE_GEN_ITEMS.length;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_260px] gap-6">
      {/* Image grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
        {MOCK_IMAGE_GEN_ITEMS.map((img) => (
          <GlassCard key={img.id} className="p-0 overflow-hidden">
            <div
              className="aspect-square relative flex items-center justify-center"
              style={{ background: "var(--bg-elevated)" }}
            >
              <svg className="absolute inset-0 w-full h-full opacity-15">
                <defs>
                  <pattern id={`vt-${img.id}`} width="20" height="20" patternUnits="userSpaceOnUse">
                    <path d="M 20 0 L 0 0 0 20" fill="none" stroke="var(--purple)" strokeWidth="0.5" />
                  </pattern>
                </defs>
                <rect width="100%" height="100%" fill={`url(#vt-${img.id})`} />
              </svg>

              <svg width="50" height="50" viewBox="0 0 50 50" className="opacity-15">
                <rect x="8" y="8" width="28" height="28" fill="none" stroke="var(--text-tertiary)" strokeWidth="1" />
                <line x1="8" y1="8" x2="14" y2="3" stroke="var(--text-tertiary)" strokeWidth="1" />
                <line x1="36" y1="8" x2="42" y2="3" stroke="var(--text-tertiary)" strokeWidth="1" />
                <rect x="14" y="3" width="28" height="28" fill="none" stroke="var(--text-tertiary)" strokeWidth="1" />
              </svg>

              {img.completed && (
                <div className="absolute top-2 right-2 w-5 h-5 rounded-full flex items-center justify-center" style={{ background: "var(--green)" }}>
                  <Check size={12} style={{ color: "var(--bg-void)" }} />
                </div>
              )}
              {!img.completed && img.progress > 0 && (
                <div className="absolute top-2 right-2">
                  <Loader2 size={16} className="animate-spin" style={{ color: "var(--purple)" }} />
                </div>
              )}
              <div className="absolute bottom-2 right-2">
                <SegmentBadge label={img.segmentId} color="var(--purple)" />
              </div>
            </div>

            <div className="px-3 py-2">
              <p className="text-[10px] font-mono truncate" style={{ color: "var(--text-secondary)" }}>
                <ImageIcon size={10} className="inline mr-1" style={{ color: "var(--purple)" }} />
                {img.prompt}
              </p>
            </div>

            <div className="h-1" style={{ background: "var(--bg-void)" }}>
              <motion.div
                className="h-full"
                style={{ background: "var(--purple)" }}
                initial={{ width: 0 }}
                animate={{ width: `${img.progress}%` }}
                transition={{ duration: 1, ease: "easeOut" as const }}
              />
            </div>
          </GlassCard>
        ))}
      </div>

      {/* Sidebar */}
      <div className="space-y-4">
        <GlassCard className="p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
            Generation Stats
          </h3>
          <div className="flex justify-center mb-4">
            <ProgressRing value={(completedCount / totalCount) * 100} size={90} color="var(--purple)" strokeWidth={7}>
              <span className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>{completedCount}</span>
              <span className="text-[8px] uppercase" style={{ color: "var(--text-secondary)" }}>Images</span>
            </ProgressRing>
          </div>

          <FilterSelect label="Model" options={[{ value: "nano-banana-2", label: "Nano Banana 2" }, { value: "seed-dream", label: "Seed Dream 4.5" }]} value={model} onChange={setModel} className="mb-3" />
          <FilterSelect label="Style Profile" options={[{ value: "holographic-hud", label: "Holographic HUD" }, { value: "cinematic", label: "Cinematic Illustration" }]} value={styleProfile} onChange={setStyleProfile} className="mb-3" />

          <div className="pt-3" style={{ borderTop: "1px solid var(--border-subtle)" }}>
            <p className="text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>Cost Tracker</p>
            <p className="text-lg font-mono" style={{ color: "var(--gold)" }}>
              ${(completedCount * 0.025).toFixed(3)} <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>/ ${(totalCount * 0.025).toFixed(2)}</span>
            </p>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
