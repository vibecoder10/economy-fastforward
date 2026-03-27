import type {
  AssetRow,
  ScriptRow,
  StageTransitionRow,
  VideoDetailViewModel,
  VideoRow,
  VideoSceneViewModel,
} from "./types";

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function rowId(value: unknown, fallback: string): string {
  if (typeof value === "string" && value) return value;
  if (typeof value === "number") return String(value);
  return fallback;
}

export function buildVideoDetailViewModel(args: {
  video: VideoRow;
  scripts: ScriptRow[];
  assets: AssetRow[];
  transitions: StageTransitionRow[];
}): VideoDetailViewModel {
  const { video, scripts, assets, transitions } = args;

  const scenes: VideoSceneViewModel[] = scripts
    .map((script, index) => {
      const sceneNumber =
        asNumber(script.scene, -1) > 0
          ? asNumber(script.scene, index + 1)
          : index + 1;

      const matchingAssets = assets.filter((asset) => {
        const assetScene = asNumber(asset.scene, -1);
        return assetScene === sceneNumber;
      });

      return {
        id: rowId(script.id, `scene-${sceneNumber}`),
        sceneNumber,
        sceneText: asString(script.scene_text),
        scriptStatus: asString(script.script_status, "unknown"),
        voiceStatus: asString(script.voice_status, "unknown"),
        voiceOverUrl: asString(script.voice_over_url) || undefined,
        assets: matchingAssets,
      };
    })
    .sort((a, b) => a.sceneNumber - b.sceneNumber);

  return {
    video,
    scenes,
    assets,
    transitions: transitions.sort((a, b) => {
      const aTime = Date.parse(asString(a.created_at));
      const bTime = Date.parse(asString(b.created_at));
      return Number.isFinite(aTime) && Number.isFinite(bTime) ? bTime - aTime : 0;
    }),
  };
}
