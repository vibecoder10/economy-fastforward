"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

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

export function DirectorProvider({ children }: { children: ReactNode }) {
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [altitude, setAltitude] = useState<Altitude>("scene");
  const [focusedShotId, setFocusedShotId] = useState<string | null>(null);
  const [pendingInitialMessage, setPendingInitialMessage] = useState<string | null>(null);

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
    }),
    [selectedVideoId, altitude, focusedShotId, pendingInitialMessage]
  );

  return <DirectorContext.Provider value={value}>{children}</DirectorContext.Provider>;
}
