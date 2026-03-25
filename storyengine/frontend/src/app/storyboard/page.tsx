"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import { MOCK_STORYBOARD_SCENES } from "@/lib/mock-data";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

export default function StoryboardReviewPage() {
  const [scenes, setScenes] = useState(MOCK_STORYBOARD_SCENES);

  const selectPanel = (sceneIdx: number, panelIdx: number) => {
    setScenes((prev) =>
      prev.map((s, i) => (i === sceneIdx ? { ...s, selectedPanel: panelIdx } : s))
    );
  };

  const approveScene = (sceneIdx: number) => {
    setScenes((prev) =>
      prev.map((s, i) => (i === sceneIdx ? { ...s, approved: true } : s))
    );
  };

  const approveAll = () => {
    setScenes((prev) => prev.map((s) => ({ ...s, approved: true })));
  };

  return (
    <motion.div className="space-y-6 pb-20" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item} className="flex items-center gap-4 flex-wrap">
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Storyboard Review
        </h1>
        <StatusPill label="Awaiting Approval" color="turquoise" pulse size="md" />
      </motion.div>

      {/* Scene list */}
      <div className="space-y-4">
        {scenes.map((scene, sceneIdx) => (
          <motion.div key={scene.sceneNumber} variants={item}>
            <GlassCard className="p-5">
              <div className="flex items-start gap-6 flex-col md:flex-row">
                {/* Left: timeline dot + text */}
                <div className="flex items-start gap-3 md:w-2/5">
                  <div
                    className="w-3 h-3 rounded-full mt-1 shrink-0"
                    style={{
                      background: scene.approved ? "var(--turquoise)" : "var(--bg-elevated)",
                      border: `2px solid ${scene.approved ? "var(--turquoise)" : "var(--text-tertiary)"}`,
                    }}
                  />
                  <div>
                    <StatusPill
                      label={`Scene ${scene.sceneNumber}`}
                      color={scene.approved ? "green" : "turquoise"}
                      size="sm"
                    />
                    <p className="text-sm mt-2 leading-relaxed" style={{ color: "var(--text-primary)" }}>
                      {scene.narrationText}
                    </p>
                  </div>
                </div>

                {/* Right: panels */}
                <div className="flex-1">
                  <div className="grid grid-cols-3 gap-2">
                    {scene.panels.map((panel, panelIdx) => {
                      const isSelected = scene.selectedPanel === panelIdx;
                      const isApprovedPanel = scene.approved && isSelected;

                      return (
                        <button
                          key={panel.id}
                          onClick={() => selectPanel(sceneIdx, panelIdx)}
                          className="aspect-video rounded-lg relative overflow-hidden transition-all"
                          style={{
                            background: "var(--bg-elevated)",
                            border: isSelected
                              ? "2px solid var(--turquoise)"
                              : "1px solid var(--border-subtle)",
                            opacity: scene.approved && !isSelected ? 0.3 : 1,
                          }}
                        >
                          {/* Holographic grid */}
                          <svg className="absolute inset-0 w-full h-full opacity-20">
                            <defs>
                              <pattern id={`sg-${panel.id}`} width="16" height="16" patternUnits="userSpaceOnUse">
                                <path d="M 16 0 L 0 0 0 16" fill="none" stroke="var(--turquoise)" strokeWidth="0.5" />
                              </pattern>
                            </defs>
                            <rect width="100%" height="100%" fill={`url(#sg-${panel.id})`} />
                          </svg>

                          {/* Diagonal cross */}
                          <svg className="absolute inset-0 w-full h-full opacity-10">
                            <line x1="0" y1="0" x2="100%" y2="100%" stroke="var(--text-tertiary)" strokeWidth="0.5" />
                            <line x1="100%" y1="0" x2="0" y2="100%" stroke="var(--text-tertiary)" strokeWidth="0.5" />
                          </svg>

                          {/* Approved checkmark */}
                          {isApprovedPanel && (
                            <div className="absolute inset-0 flex items-center justify-center bg-black/30">
                              <div
                                className="w-8 h-8 rounded-full flex items-center justify-center"
                                style={{ background: "var(--turquoise)" }}
                              >
                                <Check size={16} style={{ color: "var(--bg-void)" }} />
                              </div>
                            </div>
                          )}

                          {/* Percentage for non-selected */}
                          {scene.approved && !isSelected && (
                            <div className="absolute inset-0 flex items-center justify-center">
                              <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                                40%
                              </span>
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>

                  {/* Radio selectors + actions */}
                  <div className="flex items-center justify-between mt-3">
                    <div className="flex items-center gap-3">
                      {scene.panels.map((_, panelIdx) => (
                        <button
                          key={panelIdx}
                          onClick={() => selectPanel(sceneIdx, panelIdx)}
                          className="w-3 h-3 rounded-full transition-all"
                          style={{
                            background: scene.selectedPanel === panelIdx ? "var(--turquoise)" : "transparent",
                            border: `2px solid ${scene.selectedPanel === panelIdx ? "var(--turquoise)" : "var(--text-tertiary)"}`,
                          }}
                        />
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => approveScene(sceneIdx)}
                        disabled={scene.approved}
                        className="text-xs px-3 py-1 rounded-lg transition-all disabled:opacity-50"
                        style={{
                          border: "1px solid var(--turquoise)",
                          color: "var(--turquoise)",
                          background: scene.approved ? "var(--turquoise-dim)" : "transparent",
                        }}
                      >
                        {scene.approved ? "Approved" : "Approve"}
                      </button>
                      <button
                        className="text-xs px-3 py-1 rounded-lg"
                        style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}
                      >
                        Regenerate
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </GlassCard>
          </motion.div>
        ))}
      </div>

      {/* Fixed bottom bar */}
      <div className="fixed bottom-0 left-0 right-0 z-40 p-4 md:pl-64">
        <div className="max-w-[1400px] mx-auto">
          <button
            onClick={approveAll}
            className="w-full py-3 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            Approve All Remaining
          </button>
        </div>
      </div>
    </motion.div>
  );
}
