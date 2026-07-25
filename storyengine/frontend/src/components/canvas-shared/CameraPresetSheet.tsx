"use client";

import { useMemo } from "react";
import { Modal } from "@/components/ui/modal";
import type { Asset, CameraPresetInfo } from "@/lib/api";
import { describeCameraMove } from "./camera-utils";

/**
 * Harvested out of ScenesWorkspaceTab.tsx (DIRECTOR-CHAT-PLAN.md Task 0.2),
 * brought along with `describeCameraMove` / `humanizeCameraId` (now in
 * `./camera-utils`, shared with `ShotCard`).
 *
 * C23's one-tap camera-move sheet (checklist §2.2, UX map §4): tapping a
 * shot's camera chip opens this — pick from the curated catalog (name +
 * "best for" one-liner, straight off GET /api/camera-presets — no
 * hardcoded list here) to force that ONE shot's motion, or "Auto" to clear
 * back to camera_selector.py's earn-the-move system. Reuses the C14
 * ModelOverrideSheet pattern (same Modal, same active/manual highlight,
 * same "clear" button shape) — grouped by purpose per the UX map ("Reveal
 * / Scale / Establish / Isolation / Payoff"), `static_locked`'s empty
 * best_for gets its own "Other" group at the end.
 */
const _CAMERA_PURPOSE_ORDER = ["REVEAL", "SCALE", "ESTABLISH", "ISOLATION", "PAYOFF"];
export function CameraPresetSheet({ asset, presets, saving, onPick, onUseAuto, onClose }: {
  asset: Asset;
  presets: CameraPresetInfo[];
  saving: boolean;
  onPick: (presetId: string) => void;
  onUseAuto: () => void;
  onClose: () => void;
}) {
  const label = `S-${String(asset.scene ?? 0).padStart(2, "0")}.${asset.image_index ?? 0}`;
  const current = describeCameraMove(asset, presets);
  const groups = useMemo(() => {
    const byPurpose = new Map<string, CameraPresetInfo[]>();
    const other: CameraPresetInfo[] = [];
    for (const p of presets) {
      const purpose = _CAMERA_PURPOSE_ORDER.find((pp) => p.best_for.includes(pp));
      if (purpose) {
        if (!byPurpose.has(purpose)) byPurpose.set(purpose, []);
        byPurpose.get(purpose)!.push(p);
      } else {
        other.push(p);
      }
    }
    const ordered: { title: string; items: CameraPresetInfo[] }[] = _CAMERA_PURPOSE_ORDER
      .filter((p) => byPurpose.has(p))
      .map((p) => ({ title: p.charAt(0) + p.slice(1).toLowerCase(), items: byPurpose.get(p)! }));
    if (other.length) ordered.push({ title: "Other", items: other });
    return ordered;
  }, [presets]);
  return (
    <Modal open onClose={onClose} title={`Camera move — ${label}`} size="sm">
      <p className="text-xs mb-3" style={{ color: "var(--text-tertiary)" }}>
        {current.isManual ? "Manually picked" : `Auto (earn-the-move): ${current.label}`}
      </p>
      {presets.length === 0 && (
        <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
          Couldn&apos;t load the preset list — try again in a moment.
        </p>
      )}
      <div className="flex flex-col gap-3 max-h-96 overflow-y-auto pr-1">
        {groups.map((g) => (
          <div key={g.title}>
            <p className="text-[10px] font-semibold uppercase tracking-wide mb-1" style={{ color: "var(--text-tertiary)" }}>
              {g.title}
            </p>
            <div className="flex flex-col gap-1.5">
              {g.items.map((p) => {
                const isActive = asset.camera_preset_id === p.id;
                return (
                  <button
                    key={p.id}
                    disabled={saving}
                    onClick={() => onPick(p.id)}
                    title={p.preview || undefined}
                    className="text-left px-3 py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110 disabled:opacity-50"
                    style={{
                      background: isActive ? "rgba(139, 92, 246, 0.16)" : "rgba(255,255,255,0.04)",
                      border: isActive ? "1px solid rgba(139, 92, 246, 0.4)" : "1px solid rgba(255,255,255,0.08)",
                      color: "var(--text-primary)",
                    }}>
                    <span className="block">{p.name}{isActive ? " · manual" : ""}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      {asset.camera_preset_id && (
        <button
          onClick={onUseAuto}
          disabled={saving}
          className="mt-3 w-full text-center px-3 py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 disabled:opacity-50"
          style={{ background: "var(--bg-elevated)", color: "var(--turquoise)", border: "1px solid var(--border-subtle)" }}>
          {saving ? "Saving…" : "Use Auto (earn the move)"}
        </button>
      )}
    </Modal>
  );
}
