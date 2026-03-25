"use client";

import { useState } from "react";
import { Play, Volume2, Zap, SkipForward } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import type { Video } from "@/lib/types";

interface SoundScene {
  sceneNumber: number;
  narrationText: string;
  soundPrompt: string;
  sfxStatus: "generated" | "pending" | "skipped";
  volume: number;
}

const MOCK_SOUND_SCENES: SoundScene[] = [
  {
    sceneNumber: 1,
    narrationText:
      "In the shadowed corridors of Tehran, a decision was being made that would reshape the balance of power in the Middle East...",
    soundPrompt: "Subtle tension strings, low frequency hum, distant echo",
    sfxStatus: "generated",
    volume: 15,
  },
  {
    sceneNumber: 2,
    narrationText:
      "The sanctions had been devastating. Iran's economy contracted by 12% in a single year, the rial collapsing to historic lows...",
    soundPrompt: "Paper rustling, pen writing on parchment, soft wind",
    sfxStatus: "generated",
    volume: 12,
  },
  {
    sceneNumber: 3,
    narrationText:
      "But what Western analysts failed to understand was the parallel economy that had been quietly built over decades...",
    soundPrompt: "SKIP",
    sfxStatus: "skipped",
    volume: 0,
  },
  {
    sceneNumber: 4,
    narrationText:
      "China's Belt and Road Initiative offered Tehran exactly what it needed: an alternative financial infrastructure...",
    soundPrompt: "Industrial machinery hum, container ship horn in distance",
    sfxStatus: "pending",
    volume: 15,
  },
  {
    sceneNumber: 5,
    narrationText:
      "The IRGC-controlled conglomerates now managed over 40% of Iran's non-oil GDP, a shadow state within a state...",
    soundPrompt: "Mechanical keyboard typing, surveillance camera click, server room ambient",
    sfxStatus: "pending",
    volume: 18,
  },
  {
    sceneNumber: 6,
    narrationText:
      "And so the question remains: has the West created the very monster it sought to contain?",
    soundPrompt: "SILENCE",
    sfxStatus: "skipped",
    volume: 0,
  },
];

const SFX_STATUS_MAP: Record<string, { label: string; color: string }> = {
  generated: { label: "Generated", color: "green" },
  pending: { label: "Pending", color: "orange" },
  skipped: { label: "Skipped", color: "purple" },
};

interface SoundTabProps {
  video: Video;
}

export function SoundTab({ video }: SoundTabProps) {
  const [scenes, setScenes] = useState(MOCK_SOUND_SCENES);

  const generatedCount = scenes.filter((s) => s.sfxStatus === "generated").length;
  const skippedCount = scenes.filter((s) => s.sfxStatus === "skipped").length;
  const pendingCount = scenes.filter((s) => s.sfxStatus === "pending").length;
  const estimatedCost = generatedCount * 0.05 + pendingCount * 0.05;

  const handleVolumeChange = (index: number, value: number) => {
    setScenes((prev) =>
      prev.map((s, i) => (i === index ? { ...s, volume: value } : s))
    );
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      {/* Scene list */}
      <div className="space-y-3">
        {scenes.map((scene, idx) => {
          const sfx = SFX_STATUS_MAP[scene.sfxStatus];
          return (
            <GlassCard
              key={scene.sceneNumber}
              className="p-4"
              style={{
                borderLeftWidth: 3,
                borderLeftColor:
                  scene.sfxStatus === "generated"
                    ? "var(--green)"
                    : scene.sfxStatus === "pending"
                      ? "var(--orange)"
                      : "var(--border-subtle)",
              }}
            >
              <div className="flex items-start gap-3">
                <SegmentBadge
                  label={`S-${String(scene.sceneNumber).padStart(2, "0")}`}
                />
                <div className="flex-1 min-w-0">
                  <p
                    className="text-sm leading-relaxed mb-2 line-clamp-2"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {scene.narrationText}
                  </p>

                  {/* Sound prompt */}
                  <div
                    className="flex items-center gap-2 px-3 py-2 rounded-lg mb-2"
                    style={{ background: "var(--bg-elevated)" }}
                  >
                    <Volume2
                      size={12}
                      style={{
                        color:
                          scene.soundPrompt === "SKIP" || scene.soundPrompt === "SILENCE"
                            ? "var(--text-tertiary)"
                            : "var(--gold)",
                      }}
                    />
                    <span
                      className="text-xs font-mono flex-1"
                      style={{
                        color:
                          scene.soundPrompt === "SKIP" || scene.soundPrompt === "SILENCE"
                            ? "var(--text-tertiary)"
                            : "var(--text-secondary)",
                        fontStyle:
                          scene.soundPrompt === "SKIP" || scene.soundPrompt === "SILENCE"
                            ? "italic"
                            : "normal",
                      }}
                    >
                      {scene.soundPrompt}
                    </span>
                  </div>

                  <div className="flex items-center gap-3">
                    <StatusPill label={sfx.label} color={sfx.color} />

                    {scene.sfxStatus !== "skipped" && (
                      <div className="flex items-center gap-2 flex-1">
                        <span
                          className="text-[10px] font-mono"
                          style={{ color: "var(--text-tertiary)" }}
                        >
                          Vol
                        </span>
                        <input
                          type="range"
                          min={0}
                          max={100}
                          value={scene.volume}
                          onChange={(e) =>
                            handleVolumeChange(idx, Number(e.target.value))
                          }
                          className="flex-1 h-1 appearance-none rounded-full"
                          style={{ accentColor: "var(--turquoise)" }}
                        />
                        <span
                          className="text-[10px] font-mono w-8 text-right"
                          style={{ color: "var(--text-secondary)" }}
                        >
                          {scene.volume}%
                        </span>
                      </div>
                    )}

                    {scene.sfxStatus === "generated" && (
                      <button
                        className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0"
                        style={{
                          background: "var(--turquoise-dim)",
                          color: "var(--turquoise)",
                        }}
                      >
                        <Play size={10} />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </GlassCard>
          );
        })}
      </div>

      {/* Sidebar */}
      <div className="space-y-4">
        <GlassCard className="p-5">
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-3"
            style={{ color: "var(--text-secondary)" }}
          >
            Sound Stats
          </h3>
          <div className="space-y-3">
            {[
              { label: "Total Scenes", value: String(scenes.length) },
              { label: "SFX Generated", value: String(generatedCount), color: "var(--green)" },
              { label: "Skipped", value: String(skippedCount), color: "var(--text-tertiary)" },
              { label: "Pending", value: String(pendingCount), color: "var(--orange)" },
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

          <div
            className="pt-3 mt-3"
            style={{ borderTop: "1px solid var(--border-subtle)" }}
          >
            <p
              className="text-xs font-semibold mb-1"
              style={{ color: "var(--text-secondary)" }}
            >
              Estimated Cost
            </p>
            <p className="text-lg font-mono" style={{ color: "var(--gold)" }}>
              ${estimatedCost.toFixed(2)}
            </p>
          </div>
        </GlassCard>

        <div className="space-y-2">
          <ActionButton variant="filled" icon={Zap} className="w-full">
            Generate All SFX
          </ActionButton>
          <ActionButton variant="outline" icon={SkipForward} className="w-full">
            Skip Remaining
          </ActionButton>
        </div>
      </div>
    </div>
  );
}
