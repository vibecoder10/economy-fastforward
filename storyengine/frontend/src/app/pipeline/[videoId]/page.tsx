"use client";

import { useParams } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ProgressStepper } from "@/components/ui/ProgressStepper";
import { ActionButton } from "@/components/ui/ActionButton";
import { MOCK_VIDEOS, MOCK_SCRIPT_SCENES } from "@/lib/mock-data";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

export default function VideoDetailPage() {
  const params = useParams();
  const videoId = params.videoId as string;
  const video = MOCK_VIDEOS.find((v) => v.id === videoId) || MOCK_VIDEOS[4]; // Default to scripting video

  // Group scenes by act
  const actGroups = MOCK_SCRIPT_SCENES.reduce((acc, scene) => {
    if (!acc[scene.actNumber]) acc[scene.actNumber] = [];
    acc[scene.actNumber].push(scene);
    return acc;
  }, {} as Record<number, typeof MOCK_SCRIPT_SCENES>);

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      {/* Back link */}
      <motion.div variants={item}>
        <Link
          href="/pipeline"
          className="inline-flex items-center gap-2 text-sm transition-colors hover:text-[var(--turquoise)]"
          style={{ color: "var(--text-secondary)" }}
        >
          <ArrowLeft size={16} />
          Back to Queue
        </Link>
      </motion.div>

      {/* Header */}
      <motion.div variants={item} className="flex items-start gap-4 flex-wrap">
        <div className="flex-1">
          <h1 className="text-3xl font-display mb-2" style={{ color: "var(--text-primary)" }}>
            &ldquo;{video.title}&rdquo;
          </h1>
          <StatusPill label="Scripting" color="orange" pulse size="md" />
        </div>
      </motion.div>

      {/* Progress stepper */}
      <motion.div variants={item}>
        <ProgressStepper steps={6} currentStep={3} completedSteps={[1, 2]} />
      </motion.div>

      {/* Main content: 70/30 split */}
      <motion.div variants={item} className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6">
        {/* Left: Script scenes */}
        <div className="space-y-6">
          {Object.entries(actGroups).map(([actNum, scenes]) => (
            <div key={actNum}>
              {/* Act divider */}
              <div className="flex items-center gap-4 mb-4">
                <div className="flex-1 h-px" style={{ background: "var(--orange)", opacity: 0.3 }} />
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--orange)" }}>
                  Act {actNum}
                </span>
                <div className="flex-1 h-px" style={{ background: "var(--orange)", opacity: 0.3 }} />
              </div>

              <div className="space-y-3">
                {scenes.map((scene) => (
                  <GlassCard
                    key={scene.sceneNumber}
                    className="p-4"
                    style={{
                      borderLeftWidth: 3,
                      borderLeftColor: scene.imageGenerated ? "var(--turquoise)" : "var(--orange)",
                    }}
                  >
                    <div className="flex items-start gap-3">
                      <SegmentBadge
                        label={`S-${String(scene.sceneNumber).padStart(2, "0")}`}
                        color={scene.imageGenerated ? undefined : "var(--orange)"}
                      />
                      <div className="flex-1">
                        <p className="text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>
                          {scene.narrationText}
                        </p>
                        {scene.sources && scene.sources.length > 0 && (
                          <div className="flex gap-2 mt-2 flex-wrap">
                            {scene.sources.map((src) => (
                              <span
                                key={src}
                                className="text-[10px] font-mono px-2 py-0.5 rounded"
                                style={{
                                  background: "var(--yellow-dim)",
                                  color: "var(--yellow)",
                                }}
                              >
                                [{src}]
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Left border label */}
                    <div
                      className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-full pr-2 text-[9px] font-mono writing-vertical"
                      style={{
                        color: scene.imageGenerated ? "var(--turquoise)" : "var(--text-tertiary)",
                        writingMode: "vertical-rl",
                        textOrientation: "mixed",
                        opacity: 0.6,
                      }}
                    >
                      {scene.imageGenerated ? "image generated" : "pending"}
                    </div>
                  </GlassCard>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Right: Metadata sidebar */}
        <div className="space-y-4">
          <GlassCard className="p-5">
            <div className="space-y-3">
              {[
                { label: "Framework", value: video.framework || "Panel 2" },
                { label: "Word Count", value: String(video.wordCount || 228) },
                { label: "Scene Count", value: String(video.sceneCount || 6) },
                { label: "Est. Cost", value: `$${(video.estimatedCost || 15).toFixed(2)}` },
              ].map((row) => (
                <div key={row.label} className="flex items-center justify-between">
                  <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {row.label}
                  </span>
                  <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>
                    {row.value}
                  </span>
                </div>
              ))}
            </div>
          </GlassCard>

          <div className="space-y-2">
            <ActionButton variant="filled" className="w-full">
              Approve
            </ActionButton>
            <ActionButton variant="outline" className="w-full">
              Revise
            </ActionButton>
            <ActionButton variant="warning" className="w-full">
              Regenerate
            </ActionButton>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
