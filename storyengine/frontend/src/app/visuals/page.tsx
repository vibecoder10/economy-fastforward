"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Check, Loader2, Image as ImageIcon } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { MOCK_IMAGE_GEN_ITEMS } from "@/lib/mock-data";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.06 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const completedCount = MOCK_IMAGE_GEN_ITEMS.filter((i) => i.completed).length;
const totalCount = MOCK_IMAGE_GEN_ITEMS.length;

export default function VisualsPage() {
  const [model, setModel] = useState("nano-banana-2");
  const [styleProfile, setStyleProfile] = useState("holographic-hud");

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center gap-4 flex-wrap">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Visual Generation
        </h1>
        <StatusPill label="Generating" color="purple" pulse size="md" />
      </motion.div>

      {/* Main layout */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
        {/* Image grid */}
        <motion.div
          variants={container}
          className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3"
        >
          {MOCK_IMAGE_GEN_ITEMS.map((img) => (
            <motion.div key={img.id} variants={item}>
              <GlassCard className="p-0 overflow-hidden">
                {/* Image placeholder */}
                <div
                  className="aspect-square relative flex items-center justify-center"
                  style={{ background: "var(--bg-elevated)" }}
                >
                  {/* Holographic wireframe */}
                  <svg className="absolute inset-0 w-full h-full opacity-15">
                    <defs>
                      <pattern id={`vg-${img.id}`} width="20" height="20" patternUnits="userSpaceOnUse">
                        <path d="M 20 0 L 0 0 0 20" fill="none" stroke="var(--purple)" strokeWidth="0.5" />
                      </pattern>
                    </defs>
                    <rect width="100%" height="100%" fill={`url(#vg-${img.id})`} />
                  </svg>

                  {/* 3D wireframe box in center */}
                  <svg width="60" height="60" viewBox="0 0 60 60" className="opacity-20">
                    <rect x="10" y="10" width="35" height="35" fill="none" stroke="var(--text-tertiary)" strokeWidth="1" />
                    <line x1="10" y1="10" x2="18" y2="4" stroke="var(--text-tertiary)" strokeWidth="1" />
                    <line x1="45" y1="10" x2="53" y2="4" stroke="var(--text-tertiary)" strokeWidth="1" />
                    <line x1="45" y1="45" x2="53" y2="39" stroke="var(--text-tertiary)" strokeWidth="1" />
                    <rect x="18" y="4" width="35" height="35" fill="none" stroke="var(--text-tertiary)" strokeWidth="1" />
                  </svg>

                  {/* Completed overlay */}
                  {img.completed && (
                    <div className="absolute top-2 right-2">
                      <div
                        className="w-5 h-5 rounded-full flex items-center justify-center"
                        style={{ background: "var(--green)" }}
                      >
                        <Check size={12} style={{ color: "var(--bg-void)" }} />
                      </div>
                    </div>
                  )}

                  {/* Generating spinner */}
                  {!img.completed && img.progress > 0 && (
                    <div className="absolute top-2 right-2">
                      <Loader2 size={16} className="animate-spin-slow" style={{ color: "var(--purple)" }} />
                    </div>
                  )}

                  {/* Segment badge */}
                  <div className="absolute bottom-2 right-2">
                    <SegmentBadge label={img.segmentId} color="var(--purple)" />
                  </div>
                </div>

                {/* Prompt text */}
                <div className="px-3 py-2">
                  <p className="text-[11px] font-mono truncate" style={{ color: "var(--text-secondary)" }}>
                    <ImageIcon size={10} className="inline mr-1" style={{ color: "var(--purple)" }} />
                    {img.prompt}
                  </p>
                </div>

                {/* Progress bar */}
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
            </motion.div>
          ))}
        </motion.div>

        {/* Right sidebar */}
        <motion.div variants={item} className="space-y-4">
          <GlassCard className="p-5">
            <h3 className="text-xs font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
              Generation Stats
            </h3>

            <div className="flex justify-center mb-4">
              <ProgressRing value={(completedCount / totalCount) * 100} size={100} color="var(--purple)" strokeWidth={8}>
                <span className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>{completedCount}</span>
                <span className="text-[9px] uppercase" style={{ color: "var(--text-secondary)" }}>Images</span>
              </ProgressRing>
            </div>

            <p className="text-center text-xs mb-6" style={{ color: "var(--text-tertiary)" }}>
              Images Complete
            </p>

            <FilterSelect
              label="Model"
              options={[
                { value: "nano-banana-2", label: "Nano Banana 2" },
                { value: "seed-dream-4.5", label: "Seed Dream 4.5" },
              ]}
              value={model}
              onChange={setModel}
              className="mb-4"
            />

            <FilterSelect
              label="Style Profile"
              options={[
                { value: "holographic-hud", label: "Holographic HUD" },
                { value: "cinematic-illustration", label: "Cinematic Illustration" },
                { value: "cinematic-dossier", label: "Cinematic Dossier" },
              ]}
              value={styleProfile}
              onChange={setStyleProfile}
              className="mb-4"
            />

            <div className="pt-4" style={{ borderTop: "1px solid var(--border-subtle)" }}>
              <p className="text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>
                Cost Tracker
              </p>
              <p className="text-lg font-mono" style={{ color: "var(--gold)" }}>
                $0.000 <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>/ 2525</span>
              </p>
            </div>
          </GlassCard>
        </motion.div>
      </div>

      {/* Bottom filmstrip */}
      <motion.div variants={item}>
        <GlassCard className="p-3">
          <div className="flex gap-2 overflow-x-auto pb-1">
            {MOCK_IMAGE_GEN_ITEMS.map((img, i) => (
              <div
                key={img.id}
                className="w-16 h-10 rounded shrink-0 flex items-center justify-center transition-all"
                style={{
                  background: "var(--bg-elevated)",
                  border: !img.completed && img.progress > 0
                    ? "2px solid var(--purple)"
                    : "1px solid var(--border-subtle)",
                  boxShadow: !img.completed && img.progress > 0
                    ? "0 0 8px rgba(139, 92, 246, 0.3)"
                    : "none",
                }}
              >
                <svg width="20" height="14" viewBox="0 0 20 14" className="opacity-30">
                  <rect x="2" y="2" width="12" height="10" fill="none" stroke="var(--text-tertiary)" strokeWidth="0.5" />
                  <line x1="2" y1="2" x2="6" y2="0" stroke="var(--text-tertiary)" strokeWidth="0.5" />
                  <line x1="14" y1="2" x2="18" y2="0" stroke="var(--text-tertiary)" strokeWidth="0.5" />
                </svg>
              </div>
            ))}
          </div>
        </GlassCard>
      </motion.div>
    </motion.div>
  );
}
