"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clapperboard, Images, LayoutGrid, Mic, Music2, PlayCircle, Users } from "lucide-react";
import {
  getVideoAssets,
  getVideoScript,
  getVideoCharacters,
  getEnvironments,
  type Asset,
} from "@/lib/api";
import { toDisplayImageUrl } from "@/lib/utils";
import { SecureAudioPlayer } from "@/components/canvas-shared/SecureAudioPlayer";
import { useDirector, type RailTab } from "./DirectorContext";

type MediaMode = "boards" | "images" | "videos";

const RAIL_TABS: { id: RailTab; label: string; icon: typeof Images }[] = [
  { id: "media", label: "Media", icon: LayoutGrid },
  { id: "voice", label: "Voice", icon: Mic },
  { id: "music", label: "Music", icon: Music2 },
  { id: "cast", label: "Cast", icon: Users },
  { id: "env", label: "Environments", icon: Clapperboard },
];

/**
 * Right rail (Chunk 1.E) — five tabs, matching
 * storyengine/tasks/director-mockup/index.html `.rail` (~L1134-1317). Every
 * panel below is LIVE (real queries, real empty states) except the sub-tab
 * boundary noted on Media/Storyboards — see that panel's own comment.
 */
export function RightRail({
  videoId,
  widthPx,
  panelRef,
}: {
  videoId: string;
  /** Custom width in px from a user drag (DirectorSurface's panel-resize
   * feature). Omitted (undefined) keeps the original fixed 340px column —
   * first load with nothing saved renders byte-for-byte what it did before. */
  widthPx?: number;
  /** Forwarded so DirectorSurface can measure this column's live rendered
   * width at drag/keydown start — see PanelResizeControls.tsx. */
  panelRef?: React.RefObject<HTMLDivElement | null>;
}) {
  // Lifted into DirectorContext (was local useState) so DirectorSurface can
  // read the active tab for chat's `ui_context.railTab` — see RailTab's doc
  // in DirectorContext.tsx. Behavior here is unchanged, just where the
  // state lives.
  const { railTab: tab, setRailTab: setTab } = useDirector();

  return (
    <div
      ref={panelRef}
      style={widthPx != null ? { width: widthPx } : undefined}
      className={`flex min-w-0 flex-none flex-col border-l border-line bg-surface ${widthPx != null ? "" : "w-[340px]"}`}
    >
      <div className="flex flex-none gap-0.5 border-b border-line-soft p-[7px]">
        {RAIL_TABS.map((t) => {
          const Icon = t.icon;
          const on = tab === t.id;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`flex h-[46px] min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-[9px] transition-colors ${
                on ? "bg-turquoise/[0.12] text-turquoise" : "text-faint hover:bg-white/[0.03] hover:text-ink"
              }`}
            >
              <Icon size={15} />
              <span className="whitespace-nowrap text-[9.5px] font-semibold leading-none">{t.label}</span>
            </button>
          );
        })}
      </div>

      <div className="flex-1 overflow-y-auto p-3.5">
        {tab === "media" && <MediaPanel videoId={videoId} />}
        {tab === "voice" && <VoicePanel videoId={videoId} />}
        {tab === "music" && <MusicPanel videoId={videoId} />}
        {tab === "cast" && <CastPanel videoId={videoId} />}
        {tab === "env" && <EnvironmentsPanel videoId={videoId} />}
      </div>
    </div>
  );
}

function PanelHead({ title }: { title: string }) {
  return (
    <div className="mb-2.5 flex items-center justify-between">
      <h3 className="text-[12.5px] font-semibold text-ink">{title}</h3>
    </div>
  );
}

function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="py-3 text-[11px] leading-relaxed text-faint">{children}</p>;
}

/**
 * Media — LIVE. Storyboards/Images/Videos all read from the SAME
 * `getVideoAssets` query already used by SceneAltitudeView (React Query
 * dedupes on the shared `["video-assets", videoId]` key, so this doesn't
 * cost a second request). Storyboards has no dedicated per-scene "sheet"
 * asset in the current API — it's built here from `getVideoScript`'s
 * `storyboard_1_url..storyboard_4_url` columns per scene, which IS real
 * data (not fabricated), just a coarser shape than the mockup's 6-panel
 * grid implies.
 */
function MediaPanel({ videoId }: { videoId: string }) {
  const [mode, setMode] = useState<MediaMode>("boards");
  const assetsQuery = useQuery({ queryKey: ["video-assets", videoId], queryFn: () => getVideoAssets(videoId) });
  const scriptQuery = useQuery({ queryKey: ["video-script", videoId], queryFn: () => getVideoScript(videoId) });

  const images = (assetsQuery.data ?? []).filter((a) => a.image_url);
  const videos = (assetsQuery.data ?? []).filter((a) => a.video_clip_url);
  const boards = (scriptQuery.data ?? []).filter(
    (s) => s.storyboard_1_url || s.storyboard_2_url || s.storyboard_3_url || s.storyboard_4_url
  );

  const isLoading = assetsQuery.isLoading || scriptQuery.isLoading;

  return (
    <div>
      <PanelHead title="Media" />
      <div className="mb-2.5 flex gap-0.5 rounded-[10px] border border-line-soft bg-deep p-[3px]">
        {(["boards", "images", "videos"] as MediaMode[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={`h-[25px] flex-1 rounded-[7px] text-[11px] font-medium transition-colors ${
              mode === m
                ? "bg-turquoise/[0.14] text-turquoise shadow-[inset_0_0_0_1px_rgba(0,212,170,0.26)]"
                : "text-faint hover:text-ink"
            }`}
          >
            {m === "boards" ? "Storyboards" : m === "images" ? "Images" : "Videos"}
          </button>
        ))}
      </div>

      {isLoading && <EmptyNote>Loading…</EmptyNote>}

      {!isLoading && mode === "boards" && (
        boards.length === 0 ? (
          <EmptyNote>No storyboard sheets yet — one shows up per scene once drawn.</EmptyNote>
        ) : (
          <div className="grid grid-cols-3 gap-1.5">
            {boards.map((s) => {
              const url = toDisplayImageUrl(s.storyboard_1_url);
              return (
                <div key={s.id} className="relative aspect-square overflow-hidden rounded-[9px] border border-line-soft bg-deep">
                  {url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={url} alt="" className="absolute inset-0 h-full w-full object-cover" />
                  ) : null}
                  <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 to-transparent px-1 py-1 text-center text-[9px] text-white/90">
                    Scene {s.scene}
                  </span>
                </div>
              );
            })}
          </div>
        )
      )}

      {!isLoading && mode === "images" && (
        images.length === 0 ? (
          <EmptyNote>No finished stills yet.</EmptyNote>
        ) : (
          <div className="grid grid-cols-3 gap-1.5">
            {images.map((a) => (
              <ThumbTile key={a.id} asset={a} />
            ))}
          </div>
        )
      )}

      {!isLoading && mode === "videos" && (
        videos.length === 0 ? (
          <EmptyNote>No clips made yet.</EmptyNote>
        ) : (
          <div className="grid grid-cols-3 gap-1.5">
            {videos.map((a) => (
              <ThumbTile key={a.id} asset={a} showPlay />
            ))}
          </div>
        )
      )}
    </div>
  );
}

function ThumbTile({ asset, showPlay }: { asset: Asset; showPlay?: boolean }) {
  const url = toDisplayImageUrl(asset.image_url);
  const label = `${asset.scene ?? 0}.${asset.image_index ?? 0}`;
  return (
    <div className="relative aspect-square overflow-hidden rounded-[9px] border border-line-soft bg-deep">
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt="" className="absolute inset-0 h-full w-full object-cover" />
      ) : null}
      {showPlay && (
        <span className="absolute left-1/2 top-1/2 flex h-[22px] w-[22px] -translate-x-1/2 -translate-y-[58%] items-center justify-center rounded-full border border-white/35 bg-black/50 text-[8px] text-white">
          <PlayCircle size={12} />
        </span>
      )}
      {showPlay && asset.duration_seconds ? (
        <em className="absolute right-1 top-1 rounded-[4px] bg-black/75 px-1 py-0.5 text-[8.5px] font-bold not-italic text-white">
          {Math.round(asset.duration_seconds)}s
        </em>
      ) : null}
      <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 to-transparent px-1 py-1 text-center text-[9px] text-white/90">
        {label}
      </span>
    </div>
  );
}

/** Voice — LIVE. One SecureAudioPlayer per scene that has a voice track. */
function VoicePanel({ videoId }: { videoId: string }) {
  const scriptQuery = useQuery({ queryKey: ["video-script", videoId], queryFn: () => getVideoScript(videoId) });
  const voiced = (scriptQuery.data ?? []).filter((s) => s.voice_over_url && s.scene !== null);

  return (
    <div>
      <PanelHead title="Narration takes" />
      {scriptQuery.isLoading && <EmptyNote>Loading…</EmptyNote>}
      {!scriptQuery.isLoading && voiced.length === 0 && (
        <EmptyNote>No narration recorded yet — scenes show up here once voiced.</EmptyNote>
      )}
      {voiced.map((s) => (
        <div key={s.id} className="mb-1.5 rounded-[11px] border border-line-soft bg-deep px-2.5 py-2">
          <div className="mb-1 text-[12px] font-medium text-ink">Scene {s.scene}</div>
          <SecureAudioPlayer videoId={videoId} scene={s.scene as number} />
        </div>
      ))}
    </div>
  );
}

/**
 * Music & sound — LIVE for per-shot sound effects (`assets.sound_effect_url`
 * / `sound_prompt`), which are the only sound data this API exposes today.
 * There is no dedicated music-bed endpoint yet, so that half of the
 * mockup's "Music & sound" concept is an honest gap, not a shell — noted
 * plainly rather than invented.
 */
function MusicPanel({ videoId }: { videoId: string }) {
  const assetsQuery = useQuery({ queryKey: ["video-assets", videoId], queryFn: () => getVideoAssets(videoId) });
  const withSound = (assetsQuery.data ?? []).filter((a) => a.sound_effect_url);

  return (
    <div>
      <PanelHead title="Music & sound" />
      {assetsQuery.isLoading && <EmptyNote>Loading…</EmptyNote>}
      {!assetsQuery.isLoading && withSound.length === 0 && (
        <EmptyNote>No sound designed yet.</EmptyNote>
      )}
      {withSound.map((a) => (
        <div key={a.id} className="mb-1.5 rounded-[11px] border border-line-soft bg-deep px-2.5 py-2">
          <div className="text-[12px] font-medium text-ink">
            Scene {a.scene}, shot {a.image_index}
          </div>
          <div className="mt-0.5 text-[10.5px] text-faint">{a.sound_prompt || "Sound effect"}</div>
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <audio controls src={toDisplayImageUrl(a.sound_effect_url)} className="mt-1.5 h-7 w-full" />
        </div>
      ))}
      <p className="mt-2 text-[10.5px] leading-relaxed text-faint">
        A dedicated music bed isn&apos;t wired to this rail yet — this list is per-shot sound effects only.
      </p>
    </div>
  );
}

/** Cast — LIVE via getVideoCharacters (same call ScenesWorkspaceTab uses).
 * Tapping a tile selects that character as chat's next target (the
 * DirectorContext `selectedEntity` half of "select a shot or a character,
 * then say 'make him older'" — see DirectorContext.tsx). Tapping the
 * already-selected tile clears it, same toggle affordance as a shot's
 * focus. The selection is surfaced back to the creator by the chip near
 * the chat composer (DirectorSurface.tsx `SelectionChip`), not here — this
 * tile only needs to show ITS OWN selected state. */
function CastPanel({ videoId }: { videoId: string }) {
  const query = useQuery({ queryKey: ["video-characters-gate", videoId], queryFn: () => getVideoCharacters(videoId) });
  const characters = query.data?.characters ?? [];
  const { selectedEntity, setSelectedEntity } = useDirector();

  return (
    <div>
      <PanelHead title="Cast" />
      {query.isLoading && <EmptyNote>Loading…</EmptyNote>}
      {!query.isLoading && characters.length === 0 && <EmptyNote>No cast designed yet.</EmptyNote>}
      {characters.length > 0 && (
        <div className="grid grid-cols-3 gap-1.5">
          {characters.map((c) => {
            const on = selectedEntity?.kind === "character" && selectedEntity.id === c.id;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => setSelectedEntity(on ? null : { id: c.id, kind: "character" })}
                title={on ? `Clear ${c.name} as chat's target` : `Talk to chat about ${c.name}`}
                className="relative aspect-square overflow-hidden rounded-[9px] border bg-deep transition-colors"
                style={{ borderColor: on ? "var(--turquoise)" : undefined, boxShadow: on ? "0 0 0 1px var(--turquoise)" : undefined }}
              >
                {c.reference_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={toDisplayImageUrl(c.reference_url)} alt="" className="absolute inset-0 h-full w-full object-cover" />
                ) : null}
                <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 to-transparent px-1 py-1 text-center text-[9px] text-white/90">
                  {c.name}
                </span>
              </button>
            );
          })}
        </div>
      )}
      {characters.length > 0 && (
        <p className="mt-2.5 text-[10.5px] leading-relaxed text-faint">
          Every drawing in this video is pinned to these sheets. Change a sheet and the shots that use it get
          flagged for a redraw. Tap one to make it chat&apos;s next target.
        </p>
      )}
    </div>
  );
}

/** Environments — LIVE via getEnvironments. Same tap-to-select affordance as
 * CastPanel above, sharing the SAME `selectedEntity` field (`kind: "environment"`
 * instead of `"character"`). */
function EnvironmentsPanel({ videoId }: { videoId: string }) {
  const query = useQuery({ queryKey: ["video-environments", videoId], queryFn: () => getEnvironments(videoId) });
  const environments = useMemo(() => query.data?.environments ?? [], [query.data]);
  const { selectedEntity, setSelectedEntity } = useDirector();

  return (
    <div>
      <PanelHead title="Environments" />
      {query.isLoading && <EmptyNote>Loading…</EmptyNote>}
      {!query.isLoading && environments.length === 0 && <EmptyNote>No environments designed yet.</EmptyNote>}
      {environments.length > 0 && (
        <div className="grid grid-cols-3 gap-1.5">
          {environments.map((e) => {
            const on = selectedEntity?.kind === "environment" && selectedEntity.id === e.id;
            return (
              <button
                key={e.id}
                type="button"
                onClick={() => setSelectedEntity(on ? null : { id: e.id, kind: "environment" })}
                title={on ? `Clear ${e.name} as chat's target` : `Talk to chat about ${e.name}`}
                className="relative aspect-square overflow-hidden rounded-[9px] border bg-deep transition-colors"
                style={{ borderColor: on ? "var(--turquoise)" : undefined, boxShadow: on ? "0 0 0 1px var(--turquoise)" : undefined }}
              >
                {e.reference_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={toDisplayImageUrl(e.reference_url)} alt="" className="absolute inset-0 h-full w-full object-cover" />
                ) : null}
                <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 to-transparent px-1 py-1 text-center text-[9px] text-white/90">
                  {e.name}
                </span>
              </button>
            );
          })}
        </div>
      )}
      {environments.length > 0 && (
        <p className="mt-2.5 text-[10.5px] leading-relaxed text-faint">
          Every place the story visits, drawn once and reused. A shot set in one of these always gets this
          environment. Tap one to make it chat&apos;s next target.
        </p>
      )}
    </div>
  );
}
