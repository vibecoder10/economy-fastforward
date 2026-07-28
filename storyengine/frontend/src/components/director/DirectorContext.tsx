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

  // Keep local state in sync whenever the URL itself changes from OUTSIDE a
  // setSelectedVideoId call — browser back/forward, a fresh navigation, or
  // this same effect settling right after router.push below resolves. Safe
  // to also run on every render's derived `urlVideoId` because it only
  // fires a state update when the value actually differs (React bails out
  // of an identical setState).
  useEffect(() => {
    setSelectedVideoIdState(urlVideoId);
  }, [urlVideoId]);

  // Mounted ONCE at the root layout (see app/layout.tsx), not per-page, so
  // this provider instance survives the client-side navigation this
  // function triggers — `pendingInitialMessage`/`focusedShotId`/`altitude`
  // below are NOT reset just because the URL changed from `/chat` to
  // `/chat/<id>`. That matters concretely for DirectorHome's "describe a
  // video" box: it calls `setPendingInitialMessage(sentence)` immediately
  // before `setSelectedVideoId(video.id)` — if this provider lived inside
  // the page component instead, the navigation to `/chat/<id>` would mount
  // a BRAND NEW provider with `pendingInitialMessage` back to null, and the
  // seeded pitch would silently never reach ChatCore.
  const setSelectedVideoId = useCallback(
    (id: string | null) => {
      // Optimistic: update immediately so the canvas/chat swap in on the
      // same tick instead of waiting on the navigation to resolve. The
      // effect above re-syncs to whatever the URL ends up being, so this
      // never fights with it.
      setSelectedVideoIdState(id);
      router.push(id ? `/chat/${id}` : "/chat");
    },
    [router]
  );

  const [altitude, setAltitude] = useState<Altitude>("scene");
  const [focusedShotId, setFocusedShotId] = useState<string | null>(null);
  const [pendingInitialMessage, setPendingInitialMessage] = useState<string | null>(null);
  const [pendingInitialIntent, setPendingInitialIntent] = useState<"build" | null>(null);

  const value = useMemo<DirectorState>(
    () => ({
      selectedVideoId,
      setSelectedVideoId,
      altitude,
      setAltitude,
      focusedShotId,
      setFocusedShotId,
      pendingInitialMessage,
      setPendingInitialMessage,
      pendingInitialIntent,
      setPendingInitialIntent,
    }),
    [
      selectedVideoId,
      setSelectedVideoId,
      altitude,
      focusedShotId,
      pendingInitialMessage,
      pendingInitialIntent,
    ]
  );

  return <DirectorContext.Provider value={value}>{children}</DirectorContext.Provider>;
}
