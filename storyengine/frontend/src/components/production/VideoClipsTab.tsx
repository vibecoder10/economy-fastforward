"use client";

import { useState } from "react";
import { Check, Loader2, Play, AlertTriangle, Sparkles, Film } from "lucide-react";
import { motion } from "framer-motion";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { ActionButton } from "@/components/ui/ActionButton";
import type { Video } from "@/lib/types";

interface HeroShot {
  id: string;
  sceneNumber: number;
  videoPrompt: string;
  status: "pending" | "generating" | "done";
  duration: string;
}

const MOCK_HERO_SHOTS: HeroShot[] = [
  {
    id: "hs-1",
    sceneNumber: 3,
    videoPrompt:
      "Slow dolly into a dimly lit war room, maps and documents scattered across a mahogany table, flickering overhead light casting long shadows",
    status: "done",
    duration: "4s",
  },
  {
    id: "hs-2",
    sceneNumber: 7,
    videoPrompt:
      "Aerial tracking shot over sprawling container port at dusk, cranes moving in synchronized rhythm, golden hour light reflecting off steel",
    status: "done",
    duration: "5s",
  },
  {
    id: "hs-3",
    sceneNumber: 12,
    videoPrompt:
      "Close-up of hands signing a classified document, slow push-in revealing official seal and stamps, shallow depth of field",
    status: "generating",
    duration: "4s",
  },
  {
    id: "hs-4",
    sceneNumber: 18,
    videoPrompt:
      "Wide establishing shot of Tehran skyline at night, city lights twinkling, slow pan right revealing Milad Tower silhouette against purple sky",
    status: "pending",
    duration: "5s",
  },
];

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  done: { label: "Generated", color: "green" },
  generating: { label: "Generating", color: "purple" },
  pending: { label: "Pending", color: "orange" },
};

interface VideoClipsTabProps {
  video: Video;
}

export function VideoClipsTab({ video }: VideoClipsTabProps) {
  const [model, setModel] = useState("veo3_fast");
  const [confirmGenerate, setConfirmGenerate] = useState(false);

  const doneCount = MOCK_HERO_SHOTS.filter((h) => h.status === "done").length;
  const totalCount = MOCK_HERO_SHOTS.length;
  const progressPct = totalCount > 0 ? (doneCount / totalCount) * 100 : 0;
  const estimatedCost = totalCount * 0.3;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      {/* Clip grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {MOCK_HERO_SHOTS.map((shot) => {
          const cfg = STATUS_CONFIG[shot.status];
          return (
            <GlassCard key={shot.id} className="p-0 overflow-hidden">
              {/* Image placeholder */}
              <div
                className="aspect-video relative flex items-center justify-center"
                style={{ background: "var(--bg-elevated)" }}
              >
                {/* Holographic grid */}
                <svg className="absolute inset-0 w-full h-full opacity-10">
                  <defs>
                    <pattern
                      id={`vc-grid-${shot.id}`}
                      width="30"
                      height="30"
                      patternUnits="userSpaceOnUse"
                    >
                      <path
                        d="M 30 0 L 0 0 0 30"
                        fill="none"
                        stroke="var(--purple)"
                        strokeWidth="0.5"
                      />
                    </pattern>
                  </defs>
                  <rect width="100%" height="100%" fill={`url(#vc-grid-${shot.id})`} />
                </svg>

                {/* Status overlay */}
                {shot.status === "done" && (
                  <div
                    className="absolute top-2 right-2 w-7 h-7 rounded-full flex items-center justify-center z-10"
                    style={{ background: "rgba(0, 230, 138, 0.2)", color: "var(--green)" }}
                  >
                    <Check size={14} />
                  </div>
                )}

                {shot.status === "generating" && (
                  <motion.div
                    className="absolute inset-0 z-10 flex items-center justify-center"
                    animate={{ opacity: [0.4, 1, 0.4] }}
                    transition={{ duration: 2, repeat: Infinity }}
                  >
                    <div
                      className="w-12 h-12 rounded-full flex items-center justify-center"
                      style={{ background: "rgba(139, 92, 246, 0.25)" }}
                    >
                      <Loader2 size={20} className="animate-spin" style={{ color: "var(--purple)" }} />
                    </div>
                  </motion.div>
                )}

                {shot.status === "pending" && (
                  <Film size={28} style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
                )}

                {shot.status === "done" && (
                  <button
                    className="absolute inset-0 flex items-center justify-center z-10 opacity-0 hover:opacity-100 transition-opacity"
                    style={{ background: "rgba(0,0,0,0.5)" }}
                  >
                    <Play size={32} style={{ color: "white" }} />
                  </button>
                )}

                {/* Duration badge */}
                <span
                  className="absolute bottom-2 right-2 text-[10px] font-mono px-1.5 py-0.5 rounded z-10"
                  style={{ background: "rgba(0,0,0,0.7)", color: "var(--text-primary)" }}
                >
                  {shot.duration}
                </span>
              </div>

              {/* Prompt overlay */}
              <div className="p-3">
                <div className="flex items-center gap-2 mb-2">
                  <SegmentBadge
                    label={`S-${String(shot.sceneNumber).padStart(2, "0")}`}
                    color={shot.status === "generating" ? "var(--purple)" : undefined}
                  />
                  <StatusPill
                    label={cfg.label}
                    color={cfg.color}
                    pulse={shot.status === "generating"}
                  />
                </div>
                <p
                  className="text-[11px] leading-relaxed line-clamp-2"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {shot.videoPrompt}
                </p>
              </div>
            </GlassCard>
          );
        })}
      </div>

      {/* Sidebar */}
      <div className="space-y-4">
        {/* Stats */}
        <GlassCard className="p-5">
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-4"
            style={{ color: "var(--text-secondary)" }}
          >
            Clip Stats
          </h3>
          <div className="flex justify-center mb-4">
            <ProgressRing value={progressPct} size={90} color="var(--purple)" label="done" />
          </div>
          <div className="space-y-3">
            {[
              { label: "Total Clips", value: String(totalCount) },
              { label: "Generated", value: String(doneCount), color: "var(--green)" },
              {
                label: "Generating",
                value: String(MOCK_HERO_SHOTS.filter((h) => h.status === "generating").length),
                color: "var(--purple)",
              },
              {
                label: "Pending",
                value: String(MOCK_HERO_SHOTS.filter((h) => h.status === "pending").length),
                color: "var(--orange)",
              },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  {row.label}
                </span>
                <span
                  className="text-sm font-mono font-medium"
                  style={{ color: row.color || "var(--text-primary)" }}
                >
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Model selector */}
        <GlassCard className="p-5">
          <FilterSelect
            label="Video Model"
            options={[
              { value: "veo3_fast", label: "Veo 3.1 Fast" },
              { value: "veo3", label: "Veo 3.1 Quality" },
            ]}
            value={model}
            onChange={setModel}
          />

          <div className="pt-3 mt-3" style={{ borderTop: "1px solid var(--border-subtle)" }}>
            <p className="text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>
              Estimated Cost
            </p>
            <p className="text-lg font-mono" style={{ color: "var(--gold)" }}>
              ${estimatedCost.toFixed(2)}
            </p>
          </div>
        </GlassCard>

        {/* Warning */}
        <GlassCard className="p-4" style={{ borderColor: "var(--orange)", borderWidth: 1 }}>
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" style={{ color: "var(--orange)" }} />
            <p className="text-[11px] leading-relaxed" style={{ color: "var(--orange)" }}>
              Video generation is manual only. Each clip costs ~$0.30. Review prompts carefully before generating.
            </p>
          </div>
        </GlassCard>

        {/* Actions */}
        <div className="space-y-2">
          <ActionButton variant="outline" icon={Sparkles} className="w-full">
            Generate Prompts
          </ActionButton>
          {confirmGenerate ? (
            <ActionButton
              variant="filled"
              icon={Film}
              className="w-full"
              onClick={() => setConfirmGenerate(false)}
            >
              Confirm Generate All
            </ActionButton>
          ) : (
            <ActionButton
              variant="filled"
              icon={Film}
              className="w-full"
              onClick={() => setConfirmGenerate(true)}
            >
              Generate All Clips
            </ActionButton>
          )}
        </div>
      </div>
    </div>
  );
}
