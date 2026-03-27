import { createServiceRoleSupabaseClient } from "@/lib/supabase/server";
import { buildVideoDetailViewModel } from "./normalize";
import type {
  AssetRow,
  ScriptRow,
  StageTransitionRow,
  VideoDetailViewModel,
  VideoRow,
} from "./types";

async function maybeSelectByColumn<T extends Record<string, unknown>>(args: {
  table: string;
  column: string;
  value: string | number;
}): Promise<T[]> {
  const supabase = createServiceRoleSupabaseClient();
  const { data, error } = await supabase
    .from(args.table)
    .select("*")
    .eq(args.column, args.value);

  if (error) {
    return [];
  }

  return (data || []) as T[];
}

export async function getSupabaseVideoById(
  id: string | number
): Promise<VideoRow | null> {
  const supabase = createServiceRoleSupabaseClient();
  const { data, error } = await supabase.from("videos").select("*").eq("id", id).limit(1);

  if (error || !data || data.length === 0) {
    return null;
  }

  return data[0] as VideoRow;
}

export async function getSupabaseVideoDetail(
  id: string | number
): Promise<VideoDetailViewModel | null> {
  const video = await getSupabaseVideoById(id);
  if (!video) return null;

  const videoId = video.id ?? id;
  const title = typeof video.video_title === "string" ? video.video_title : "";

  const [scriptsByVideoId, assetsByVideoId, transitionsByVideoId] = await Promise.all([
    maybeSelectByColumn<ScriptRow>({ table: "scripts", column: "video_id", value: videoId }),
    maybeSelectByColumn<AssetRow>({ table: "assets", column: "video_id", value: videoId }),
    maybeSelectByColumn<StageTransitionRow>({
      table: "stage_transitions",
      column: "video_id",
      value: videoId,
    }),
  ]);

  const scripts =
    scriptsByVideoId.length > 0 || !title
      ? scriptsByVideoId
      : await maybeSelectByColumn<ScriptRow>({ table: "scripts", column: "title", value: title });

  const assets =
    assetsByVideoId.length > 0 || !title
      ? assetsByVideoId
      : await maybeSelectByColumn<AssetRow>({
          table: "assets",
          column: "video_title",
          value: title,
        });

  const transitions = transitionsByVideoId;

  return buildVideoDetailViewModel({
    video,
    scripts,
    assets,
    transitions,
  });
}
