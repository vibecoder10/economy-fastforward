export type StaticDocuStageKey = "roster" | "research" | "script" | "voice" | "pictures" | "video";

export const STATIC_DOCU_STAGE_TO_TAB: Record<StaticDocuStageKey, string> = {
  roster: "roster",
  research: "research",
  script: "script-voice",
  voice: "script-voice",
  pictures: "pictures",
  video: "video",
};

export function resolveStaticDocuStage(
  currentTab: string,
  preferredStage: StaticDocuStageKey | null,
): StaticDocuStageKey {
  if (preferredStage && STATIC_DOCU_STAGE_TO_TAB[preferredStage] === currentTab) {
    return preferredStage;
  }
  return (Object.entries(STATIC_DOCU_STAGE_TO_TAB)
    .find(([, tab]) => tab === currentTab)?.[0] as StaticDocuStageKey | undefined) || "roster";
}

function rosterLabel(item: unknown): string {
  if (typeof item === "string") return item.trim();
  if (!item || typeof item !== "object") return "";
  const row = item as Record<string, unknown>;
  return [row.designation, row.name || row.unit || row.machine]
    .filter(Boolean)
    .map(String)
    .join(" ")
    .trim();
}

export function staticDocuPictureTitle(
  captionTitle: string | null | undefined,
  rosterItem: unknown,
  scene: number,
): string {
  return captionTitle?.trim() || rosterLabel(rosterItem) || `Scene ${scene}`;
}
