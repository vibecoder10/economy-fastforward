"use client";

import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ActionButton } from "@/components/ui/ActionButton";
import { MOCK_SCRIPT_SCENES } from "@/lib/mock-data";
import type { Video } from "@/lib/types";

interface ScriptTabProps {
  video: Video;
}

export function ScriptTab({ video }: ScriptTabProps) {
  const actGroups = MOCK_SCRIPT_SCENES.reduce((acc, scene) => {
    if (!acc[scene.actNumber]) acc[scene.actNumber] = [];
    acc[scene.actNumber].push(scene);
    return acc;
  }, {} as Record<number, typeof MOCK_SCRIPT_SCENES>);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      {/* Script scenes */}
      <div className="space-y-6">
        {Object.entries(actGroups).map(([actNum, scenes]) => (
          <div key={actNum}>
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
                              style={{ background: "var(--yellow-dim)", color: "var(--yellow)" }}
                            >
                              [{src}]
                            </span>
                          ))}
                        </div>
                      )}
                      <div className="flex items-center gap-3 mt-2">
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          {scene.visualStyle}
                        </span>
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          {scene.composition}
                        </span>
                      </div>
                    </div>
                  </div>
                </GlassCard>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Metadata sidebar */}
      <div className="space-y-4">
        <GlassCard className="p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>
            Script Details
          </h3>
          <div className="space-y-3">
            {[
              { label: "Framework", value: video.framework || "—" },
              { label: "Word Count", value: String(video.wordCount || 0) },
              { label: "Scene Count", value: String(video.sceneCount || 0) },
              { label: "Target Length", value: `${video.videoLengthMin || 0} min` },
              { label: "Est. Cost", value: `$${(video.estimatedCost || 0).toFixed(2)}` },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{row.label}</span>
                <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>{row.value}</span>
              </div>
            ))}
          </div>
        </GlassCard>

        <div className="space-y-2">
          <ActionButton variant="filled" className="w-full">Approve Script</ActionButton>
          <ActionButton variant="outline" className="w-full">Request Revision</ActionButton>
          <ActionButton variant="warning" className="w-full">Regenerate</ActionButton>
        </div>
      </div>
    </div>
  );
}
