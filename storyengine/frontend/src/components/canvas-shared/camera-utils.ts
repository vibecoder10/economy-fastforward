import type { Asset, CameraPresetInfo } from "@/lib/api";

/**
 * Camera-move helpers. Harvested out of ScenesWorkspaceTab.tsx
 * (DIRECTOR-CHAT-PLAN.md Task 0.2) so `CameraPresetSheet` and `ShotCard`
 * can share them without one importing from the other's old home.
 */

/** Humanize a camera_moves.py catalog id ("crash_zoom_in" -> "Crash Zoom
 * In") — the chip's fallback label when a move isn't in the curated preset
 * list fetched from GET /api/camera-presets (e.g. the auto pick landed on
 * a full-catalog move outside the curated dozen). */
export function humanizeCameraId(id: string): string {
  return id.split("_").map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(" ");
}

/** The camera-move chip's display text + whether it's a manual (vs auto)
 * pick (checklist §2.2/C23). Reads `camera_preset_id` (the creator's
 * manual override) first; falls back to `camera_movement` (the AUTO/
 * "earned" pick camera_selector.py stamps at shot-plan time — raw shape
 * "move_id|PURPOSE" or "static"); "Auto" when neither exists. Fail-safe by
 * construction — every branch returns a label, so a shot with no camera
 * data at all still renders an "Auto" chip, never a broken one. */
export function describeCameraMove(asset: Asset, presets: CameraPresetInfo[]): { label: string; isManual: boolean } {
  if (asset.camera_preset_id) {
    const preset = presets.find((p) => p.id === asset.camera_preset_id);
    return { label: preset?.name ?? humanizeCameraId(asset.camera_preset_id), isManual: true };
  }
  const raw = (asset.camera_movement || "").trim();
  if (!raw) return { label: "Auto", isManual: false };
  if (raw === "static") return { label: "Static", isManual: false };
  const moveId = raw.split("|")[0];
  const preset = presets.find((p) => p.id === moveId);
  return { label: preset?.name ?? humanizeCameraId(moveId), isManual: false };
}
