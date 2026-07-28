"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import type { PendingInitialTurn } from "@/components/chat/ChatCore";

/**
 * Altitude the Director canvas is currently viewing at.
 *
 * IMPORTANT — this intentionally diverges from DIRECTOR-CHAT-PLAN.md, which
 * lists `"board" | "shot" | "timeline"`. The approved mockup
 * (storyengine/tasks/director-mockup/index.html, `.segbar` / `.seg` tabs,
 * line ~759) renders the three tabs as literal copy "Shot | Scene |
 * Timeline" with Scene active by default (`class="seg on" data-tab="scene"`).
 * The mockup is the spec of record for Chunk 1.A, so the middle altitude
 * here is "scene", not "board".
 */
export type Altitude = "shot" | "scene" | "timeline";

/** Which right-rail tab is active (RightRail.tsx `RailTab`, mirrored here so
 * DirectorSurface can read it for `ui_context.railTab` without RightRail
 * importing DirectorContext just to announce its own tab — the state now
 * LIVES here and RightRail reads/writes it via useDirector(), same pattern
 * as `altitude`. Kept as a plain string union, not re-exported from
 * RightRail, to avoid a circular import between the two files. */
export type RailTab = "media" | "voice" | "music" | "cast" | "env";

/** A character or environment picked in the right rail's Cast/Environments
 * tab (RightRail.tsx `CastPanel`/`EnvironmentsPanel`) — the second half of
 * "select a shot or a character, then say 'make him older'" alongside
 * `focusedShotId`. `kind` disambiguates the id: `video_characters.id` and
 * `video_environments.id` are separate id spaces, so a bare id alone can't
 * say which table (or which chat `ui_context.selectedEntityId` resolver
 * path) it belongs to. */
export interface SelectedEntity {
  id: string;
  kind: "character" | "environment";
}

export interface DirectorState {
  /** The video currently open on the Director surface. `null` means the
   * home screen (`DirectorHome`) should render instead of the two-column
   * chat/canvas layout — see DirectorSurface.tsx. */
  selectedVideoId: string | null;
  setSelectedVideoId: (id: string | null) => void;

  /** Which of the three canvas tabs (Shot / Scene / Timeline) is active. */
  altitude: Altitude;
  setAltitude: (a: Altitude) => void;

  /** The shot (assets.id) currently focused, e.g. via chat `@` reference or
   * clicking into Shot altitude. `null` when nothing is focused. */
  focusedShotId: string | null;
  setFocusedShotId: (id: string | null) => void;

  /** The character or environment currently selected in the right rail's
   * Cast/Environments tab. Mutually exclusive with `focusedShotId` in the
   * UI (selecting one clears the other — see RightRail.tsx's click
   * handlers) so chat's `ui_context` never has to arbitrate two live
   * targets at once. `null` when nothing is selected. */
  selectedEntity: SelectedEntity | null;
  setSelectedEntity: (entity: SelectedEntity | null) => void;

  /** Which right-rail tab is active — see the `RailTab` doc above. */
  railTab: RailTab;
  setRailTab: (tab: RailTab) => void;

  /** A one-sentence pitch typed into the DirectorHome entry box, waiting to be
   * seeded as the opening chat turn once DirectorSurface mounts ChatCore for
   * the video that box just created. Consumed exactly once (DirectorSurface
   * clears it right after handing it to ChatCore) so switching to a
   * DIFFERENT video afterwards (e.g. via "Recent videos") never resends a
   * stale pitch into an unrelated conversation. `null` the rest of the time. */
  pendingInitialMessage: string | null;
  setPendingInitialMessage: (message: string | null) => void;

  /** The declared intent for `pendingInitialMessage`, when the box that
   * produced it already KNOWS what should happen — today, only "build":
   * PromptEntrySection's plain-description box (DirectorHome.tsx) creates a
   * brand-new video and means "build the whole thing", full stop. That is
   * not a guess for the chat classifier to make (see the root-cause note in
   * backend/routes/chat.py `_handle_copilot`, `explicit_verb`) — so it rides
   * alongside the seeded message and ChatCore's mount effect passes it
   * straight through as `ChatTurnRequest.explicit_verb`. `null` for every
   * other producer of `pendingInitialMessage` (e.g. the YouTube "Model it"
   * confirm, which already has its own explicit paid-confirm gate and a
   * different first move) and consumed once, same lifecycle as the message
   * itself. */
  pendingInitialIntent: "build" | null;
  setPendingInitialIntent: (intent: "build" | null) => void;

  /** The RESULT (in-flight, done, or errored) of the seed turn ChatCore's
   * `initialMessage` effect fires for `pendingInitialMessage` above — see
   * ChatCore.tsx's `PendingInitialTurn` doc comment for the full root-cause
   * story. Lives here, not in ChatCore's own local state, because
   * DirectorHome's entry box hands off across a REAL Next.js navigation
   * (`/` or `/chat` -> `/chat/<id>`, `setSelectedVideoId` below) that
   * unmounts the ChatCore instance that started the turn well before its
   * `/api/chat` response lands — losing that response used to mean the
   * result never rendered until a manual refresh. DirectorProvider is
   * mounted once at the root layout, so this state (unlike ChatCore's own)
   * survives that navigation intact for the replacement instance to read.
   * `null` whenever no seed turn is in flight/pending consumption — the
   * common case. */
  pendingInitialTurn: PendingInitialTurn | null;
  setPendingInitialTurn: (turn: PendingInitialTurn | null) => void;
}

const DirectorContext = createContext<DirectorState | null>(null);

export function useDirector(): DirectorState {
  const ctx = useContext(DirectorContext);
  if (!ctx) {
    throw new Error(
      "useDirector() was called outside a <DirectorProvider>. Wrap the tree " +
        "that renders DirectorSurface (or anything under it) in " +
        "<DirectorProvider> — see components/director/DirectorContext.tsx."
    );
  }
  return ctx;
}

// The URL prefix a video lives under once the Director surface has one open.
// Chosen to match this codebase's existing convention for "a page about one
// specific video" (`/pipeline/[videoId]`, `/scene-control/[videoId]`) rather
// than a query string — every other entity-scoped route here is a path
// segment, never `?videoId=`. `/chat` (no id) is the video-less home screen,
// already wired as a full-bleed route in AuthenticatedShell before this fix.
const CHAT_VIDEO_PREFIX = "/chat/";

function videoIdFromPathname(pathname: string | null): string | null {
  if (!pathname || !pathname.startsWith(CHAT_VIDEO_PREFIX)) return null;
  const rest = pathname.slice(CHAT_VIDEO_PREFIX.length);
  const id = rest.split("/")[0];
  return id || null;
}

export function DirectorProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const urlVideoId = videoIdFromPathname(pathname);

  // The URL is the source of truth for which video is open — NOT a plain
  // useState with nothing backing it. That was the root cause of the
  // "refresh loses the Director chat" bug (verified live, 2026-07-27): with
  // no id anywhere in the address bar, a refresh always re-mounts this
  // provider with no way to know which video was open, so it fell back to
  // the empty DirectorHome. Seeding local state from `urlVideoId` here means
  // a fresh load (or a refresh, or pasting the URL in a new tab) starts
  // already pointed at the right video — no flash of the home screen while
  // some effect catches up.
  const [selectedVideoId, setSelectedVideoIdState] = useState<string | null>(urlVideoId);

  // Declared here (ahead of the effect and callback below that both reset
  // it) rather than down with the rest of the plain useState fields, so the
  // video-id-changed -> altitude-reset relationship reads top to bottom
  // instead of forward-referencing a declaration two sections down.
  const [altitude, setAltitude] = useState<Altitude>("scene");

  // Keep local state in sync whenever the URL itself changes from OUTSIDE a
  // setSelectedVideoId call — browser back/forward, a fresh navigation, or
  // this same effect settling right after router.push below resolves. Safe
  // to also run on every render's derived `urlVideoId` because it only
  // fires a state update when the value actually differs (React bails out
  // of an identical setState).
  useEffect(() => {
    setSelectedVideoIdState(urlVideoId);
    // Bug fix (2026-07-27, live: a brand-new video with 0 scenes/0 shots
    // opened on the Shot tab's "not designed yet" placeholder instead of the
    // working Scene board). Root cause: `altitude` below is a single
    // useState living in this once-mounted provider (see the comment on
    // `setSelectedVideoId`) — nothing ever reset it when the video changed,
    // so whichever tab a PRIOR video was left on (e.g. Shot or Timeline,
    // both real, clickable tabs) silently carried forward onto the next
    // video opened, including a fresh one that had never been on any tab at
    // all. This covers browser back/forward and any other path that changes
    // the URL's video id directly (bypassing `setSelectedVideoId` below,
    // which handles the same reset for its own programmatic-navigation
    // callers). Scene is the only altitude with a real, built view
    // (CanvasStage.tsx) — every video should always open there.
    setAltitude("scene");
  }, [urlVideoId]);

  // Mounted ONCE at the root layout (see app/layout.tsx), not per-page, so
  // this provider instance survives the client-side navigation this
  // function triggers — `pendingInitialMessage`/`focusedShotId` below are
  // NOT reset just because the URL changed from `/chat` to `/chat/<id>`.
  // That matters concretely for DirectorHome's "describe a video" box: it
  // calls `setPendingInitialMessage(sentence)` immediately before
  // `setSelectedVideoId(video.id)` — if this provider lived inside the page
  // component instead, the navigation to `/chat/<id>` would mount a BRAND
  // NEW provider with `pendingInitialMessage` back to null, and the seeded
  // pitch would silently never reach ChatCore. `altitude` is the deliberate
  // exception (see below): a canvas tab is a per-video view, not a
  // cross-video intent like a pending pitch, so it's reset on every id
  // change instead of surviving one.
  const setSelectedVideoId = useCallback(
    (id: string | null) => {
      // Optimistic: update immediately so the canvas/chat swap in on the
      // same tick instead of waiting on the navigation to resolve. The
      // effect above re-syncs to whatever the URL ends up being, so this
      // never fights with it.
      setSelectedVideoIdState(id);
      // Reset in this same batch (not left to the urlVideoId effect above)
      // so there's no one-frame flash of the new video rendered under the
      // OLD altitude tab before the effect catches up — see the effect's
      // comment for the full root-cause story of why this reset exists.
      setAltitude("scene");
      router.push(id ? `/chat/${id}` : "/chat");
    },
    [router]
  );

  const [focusedShotId, setFocusedShotIdRaw] = useState<string | null>(null);
  const [selectedEntity, setSelectedEntityRaw] = useState<SelectedEntity | null>(null);
  const [railTab, setRailTab] = useState<RailTab>("media");
  const [pendingInitialMessage, setPendingInitialMessage] = useState<string | null>(null);
  const [pendingInitialIntent, setPendingInitialIntent] = useState<"build" | null>(null);
  const [pendingInitialTurn, setPendingInitialTurn] = useState<PendingInitialTurn | null>(null);

  // A shot and an entity (character/environment) are mutually exclusive as
  // chat's next target — picking one clears the other here, centrally, so
  // every caller (SceneAltitudeView's shot `onTap`, RightRail's Cast/
  // Environments tiles) gets the exclusivity for free instead of each
  // remembering to clear the other field itself.
  const setFocusedShotId = (id: string | null) => {
    setFocusedShotIdRaw(id);
    if (id !== null) setSelectedEntityRaw(null);
  };
  const setSelectedEntity = (entity: SelectedEntity | null) => {
    setSelectedEntityRaw(entity);
    if (entity !== null) setFocusedShotIdRaw(null);
  };

  const value = useMemo<DirectorState>(
    () => ({
      selectedVideoId,
      setSelectedVideoId,
      altitude,
      setAltitude,
      focusedShotId,
      setFocusedShotId,
      selectedEntity,
      setSelectedEntity,
      railTab,
      setRailTab,
      pendingInitialMessage,
      setPendingInitialMessage,
      pendingInitialIntent,
      setPendingInitialIntent,
      pendingInitialTurn,
      setPendingInitialTurn,
    }),
    [
      selectedVideoId,
      setSelectedVideoId,
      altitude,
      focusedShotId,
      selectedEntity,
      railTab,
      pendingInitialMessage,
      pendingInitialIntent,
      pendingInitialTurn,
    ]
  );

  return <DirectorContext.Provider value={value}>{children}</DirectorContext.Provider>;
}
