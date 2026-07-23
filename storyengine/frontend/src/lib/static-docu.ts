export interface StaticDocuCaption {
  title?: string;
  sub?: string;
  specs?: string[];
  view_role?: string;
  view_label?: string;
  target_views?: number;
  minimum_views?: number;
}

export interface StaticDocuAssetLike {
  scene: number | null;
  image_index: number | null;
  image_url: string | null;
  status: string | null;
  generation_method?: string | null;
  caption?: string | null;
}

export type StaticDocuUnitStatus = "ready" | "generating" | "blocked" | "not_started";

export interface StaticDocuUnitState<T extends StaticDocuAssetLike> {
  scene: number;
  assets: T[];
  readyViews: number;
  targetViews: number;
  minimumViews: number;
  blockedViews: number;
  generatingViews: number;
  status: StaticDocuUnitStatus;
}

export interface StaticDocuReadiness<T extends StaticDocuAssetLike> {
  units: StaticDocuUnitState<T>[];
  totalUnits: number;
  readyUnits: number;
  blockedUnits: number;
  generatingUnits: number;
  readyViews: number;
  totalViews: number;
  allReady: boolean;
}

const BLOCKED_VIEW_STATUSES = new Set(["blocked_no_reference", "qa_rejected"]);

/** Caption is JSONB in Postgres but arrives from /assets as caption::text. */
export function parseStaticDocuCaption(
  raw: string | null | undefined,
): StaticDocuCaption | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const caption = parsed as StaticDocuCaption;
    return {
      ...caption,
      specs: Array.isArray(caption.specs)
        ? caption.specs.filter((spec): spec is string => typeof spec === "string" && spec.trim().length > 0)
        : undefined,
    };
  } catch {
    return null;
  }
}

export function groupStaticDocuAssets<T extends StaticDocuAssetLike>(
  assets: T[],
): Map<number, T[]> {
  const grouped = new Map<number, T[]>();
  for (const asset of assets) {
    if (asset.scene == null) continue;
    // Null is retained for legacy static-documentary rows created before the
    // generation_method column was selected by the API.
    if (asset.generation_method && asset.generation_method !== "static_docu") continue;
    const existing = grouped.get(asset.scene) ?? [];
    existing.push(asset);
    grouped.set(asset.scene, existing);
  }
  for (const rows of grouped.values()) {
    rows.sort((a, b) => (a.image_index ?? 999) - (b.image_index ?? 999));
  }
  return grouped;
}

function positiveCaptionNumber<T extends StaticDocuAssetLike>(
  assets: T[],
  field: "minimum_views" | "target_views",
): number | null {
  for (const asset of assets) {
    const value = parseStaticDocuCaption(asset.caption)?.[field];
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
      return Math.floor(value);
    }
  }
  return null;
}

export function getStaticDocuUnitStates<T extends StaticDocuAssetLike>(
  assets: T[],
  requestedScenes: number[] = [],
): StaticDocuUnitState<T>[] {
  const grouped = groupStaticDocuAssets(assets);
  const sceneNumbers = new Set(requestedScenes.filter((scene) => scene > 0));
  for (const scene of grouped.keys()) sceneNumbers.add(scene);

  return Array.from(sceneNumbers)
    .sort((a, b) => a - b)
    .map((scene) => {
      const unitAssets = grouped.get(scene) ?? [];
      // Legacy DvsU rows have no view contract and remain valid with one image.
      const minimumViews = positiveCaptionNumber(unitAssets, "minimum_views") ?? 1;
      const targetViews = positiveCaptionNumber(unitAssets, "target_views")
        ?? Math.max(minimumViews, unitAssets.length || 1);
      const readyViews = unitAssets.filter(
        (asset) => asset.status === "done" && Boolean(asset.image_url),
      ).length;
      const blockedViews = unitAssets.filter(
        (asset) => BLOCKED_VIEW_STATUSES.has(asset.status ?? ""),
      ).length;
      const generatingViews = unitAssets.filter(
        (asset) => asset.status === "generating",
      ).length;

      let status: StaticDocuUnitStatus = "not_started";
      if (readyViews >= minimumViews) status = "ready";
      else if (generatingViews > 0) status = "generating";
      else if (blockedViews > 0) status = "blocked";

      return {
        scene,
        assets: unitAssets,
        readyViews,
        targetViews,
        minimumViews,
        blockedViews,
        generatingViews,
        status,
      };
    });
}

export function getStaticDocuReadiness<T extends StaticDocuAssetLike>(
  assets: T[],
  requestedScenes: number[] = [],
): StaticDocuReadiness<T> {
  const units = getStaticDocuUnitStates(assets, requestedScenes);
  const readyUnits = units.filter((unit) => unit.status === "ready").length;
  return {
    units,
    totalUnits: units.length,
    readyUnits,
    blockedUnits: units.filter((unit) => unit.status === "blocked").length,
    generatingUnits: units.filter((unit) => unit.status === "generating").length,
    readyViews: units.reduce((sum, unit) => sum + unit.readyViews, 0),
    totalViews: units.reduce((sum, unit) => sum + unit.assets.length, 0),
    allReady: units.length > 0 && readyUnits === units.length,
  };
}

export function staticDocuViewLabel(
  caption: StaticDocuCaption | null,
  imageIndex: number | null,
): string {
  if (caption?.view_label) return caption.view_label;
  if (caption?.view_role === "three_quarter") return "Three-quarter";
  if (caption?.view_role === "top_oblique") return "Top-oblique";
  if (caption?.view_role === "engineering_detail") return "Detail";
  if (imageIndex === 1) return "Primary view";
  return imageIndex ? `View ${imageIndex}` : "View";
}
