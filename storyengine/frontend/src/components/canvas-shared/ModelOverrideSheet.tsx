"use client";

import { Modal } from "@/components/ui/modal";
import type { Asset } from "@/lib/api";

/**
 * Harvested out of ScenesWorkspaceTab.tsx (DIRECTOR-CHAT-PLAN.md Task 0.2).
 *
 * C14's one-tap override sheet: tapping a scene's model badge opens this —
 * pick any wired model (name + $/clip, straight off GET /api/models — no
 * hardcoded prices) to force that scene through it, or "Use recommendation"
 * to clear back to the automatic router/video default.
 */
export function ModelOverrideSheet({ asset, models, videoDefaultModel, saving, onPick, onUseRecommendation, onClose }: {
  asset: Asset;
  models: { id: string; label: string }[];
  videoDefaultModel: string;
  saving: boolean;
  onPick: (modelId: string) => void;
  onUseRecommendation: () => void;
  onClose: () => void;
}) {
  const label = `S-${String(asset.scene ?? 0).padStart(2, "0")}.${asset.image_index ?? 0}`;
  const activeId = asset.model_override || asset.routed_model || videoDefaultModel;
  const reason = asset.model_override
    ? "Manually overridden"
    : asset.routing_reason || "Channel default — no per-scene routing yet";
  return (
    <Modal open onClose={onClose} title={`Clip model — ${label}`} size="sm">
      <p className="text-xs mb-3" style={{ color: "var(--text-tertiary)" }}>{reason}</p>
      <div className="flex flex-col gap-1.5">
        {models.map((m) => {
          const isActive = m.id === activeId;
          return (
            <button
              key={m.id}
              disabled={saving}
              onClick={() => onPick(m.id)}
              className="text-left px-3 py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110 disabled:opacity-50"
              style={{
                background: isActive ? "rgba(139, 92, 246, 0.16)" : "rgba(255,255,255,0.04)",
                border: isActive ? "1px solid rgba(139, 92, 246, 0.4)" : "1px solid rgba(255,255,255,0.08)",
                color: "var(--text-primary)",
              }}>
              {m.label}{isActive && asset.model_override ? " · manual" : isActive ? " · current" : ""}
            </button>
          );
        })}
      </div>
      {asset.model_override && (
        <button
          onClick={onUseRecommendation}
          disabled={saving}
          className="mt-3 w-full text-center px-3 py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 disabled:opacity-50"
          style={{ background: "var(--bg-elevated)", color: "var(--turquoise)", border: "1px solid var(--border-subtle)" }}>
          {saving ? "Saving…" : "Use recommendation"}
        </button>
      )}
    </Modal>
  );
}
