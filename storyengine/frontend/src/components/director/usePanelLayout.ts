"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Resizable/hideable chat + rail columns for the Director surface
 * (DirectorSurface.tsx). Follows the existing `se_*` localStorage prefix
 * convention (see pipeline/page.tsx's `se_active_tenant`, ChatCore's
 * `se_pipeline_chat_open`) — versioned so a future shape change can't
 * collide with a stale saved value.
 */
const STORAGE_KEY = "se_director_panel_layout_v1";

// Tailwind's `lg:` breakpoint (default 1024px) — the point below which the
// columns stack and resizing/collapsing stops meaning anything.
const LG_QUERY = "(min-width: 1024px)";

export const CHAT_MIN_WIDTH = 260;
// Capped at 480 (not a more generous 640+) so that chat-max + rail-max +
// the canvas's own floor (CANVAS_MIN_WIDTH, DirectorSurface.tsx) still
// leaves the canvas close to usable on a real, sidebar-EXPANDED 1280px-wide
// window — the tightest realistic case, since the app sidebar reserves
// 240px when expanded (AuthenticatedShell.tsx, commit 692212db). Dragging
// both panels to their absolute max on a narrower window can still push the
// row wider than the viewport; the canvas's own min-width floor keeps the
// CostDial itself from ever breaking even then — see DirectorSurface.tsx.
export const CHAT_MAX_WIDTH = 480;
const CHAT_COLLAPSE_AT = 180; // drag-release below this snaps the chat column closed

export const RAIL_MIN_WIDTH = 240;
export const RAIL_MAX_WIDTH = 420;
const RAIL_COLLAPSE_AT = 170; // drag-release below this snaps the rail column closed

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

interface PanelLayoutState {
  /** null = no custom width yet — render the original responsive default. */
  chatWidth: number | null;
  railWidth: number | null;
  chatCollapsed: boolean;
  railCollapsed: boolean;
}

const DEFAULT_STATE: PanelLayoutState = {
  chatWidth: null,
  railWidth: null,
  chatCollapsed: false,
  railCollapsed: false,
};

function isPanelLayoutState(value: unknown): value is PanelLayoutState {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    (v.chatWidth === null || typeof v.chatWidth === "number") &&
    (v.railWidth === null || typeof v.railWidth === "number") &&
    typeof v.chatCollapsed === "boolean" &&
    typeof v.railCollapsed === "boolean"
  );
}

function loadStoredState(): PanelLayoutState {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_STATE;
    const parsed: unknown = JSON.parse(raw);
    return isPanelLayoutState(parsed) ? parsed : DEFAULT_STATE;
  } catch {
    // Corrupt value or localStorage unavailable (private mode, quota) —
    // fall back to defaults rather than crash the surface.
    return DEFAULT_STATE;
  }
}

/**
 * Drives DirectorSurface's draggable seams + collapse toggles.
 *
 * `hydrated` gates everything: until the first client effect runs, the
 * caller should render the ORIGINAL static layout untouched (no inline
 * widths, no stub swaps). Server and first-paint client output are then
 * identical (no hydration mismatch), and a visitor with nothing saved sees
 * exactly today's layout — satisfied trivially since DEFAULT_STATE mirrors
 * the original markup (null width = default classes, collapsed = false).
 *
 * `isLgUp` mirrors Tailwind's `lg:` breakpoint via matchMedia so collapse
 * only ever takes visual effect at that width or above — below it the
 * columns always render in full, stacked, matching the pre-existing
 * `flex-col lg:flex-row` behavior (a collapsed column with no way back on a
 * narrow viewport would be a bug, not a feature).
 */
export function usePanelLayout() {
  const [hydrated, setHydrated] = useState(false);
  const [isLgUp, setIsLgUp] = useState(true);
  const [state, setState] = useState<PanelLayoutState>(DEFAULT_STATE);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    setState(loadStoredState());
    setHydrated(true);

    const mql = window.matchMedia(LG_QUERY);
    setIsLgUp(mql.matches);
    const onChange = (e: MediaQueryListEvent) => setIsLgUp(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  const persist = useCallback((next: PanelLayoutState) => {
    setState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Best-effort only — a full/blocked localStorage should never crash
      // the surface, it just won't remember next time.
    }
  }, []);

  // Live drag feedback — updates on-screen width every pointermove, but
  // never touches localStorage (would be dozens of writes per drag).
  const liveResizeChat = useCallback((rawPx: number) => {
    setState((prev) => ({ ...prev, chatWidth: clamp(rawPx, CHAT_MIN_WIDTH, CHAT_MAX_WIDTH) }));
  }, []);
  const liveResizeRail = useCallback((rawPx: number) => {
    setState((prev) => ({ ...prev, railWidth: clamp(rawPx, RAIL_MIN_WIDTH, RAIL_MAX_WIDTH) }));
  }, []);

  // Commit — called on pointerup / keyboard nudge. Below the min, instead of
  // leaving a broken sliver, it snaps shut; the last real width is kept in
  // state so re-expanding restores roughly where the user left it.
  const commitResizeChat = useCallback(
    (rawPx: number) => {
      if (rawPx < CHAT_COLLAPSE_AT) {
        persist({ ...stateRef.current, chatCollapsed: true });
        return;
      }
      persist({ ...stateRef.current, chatWidth: clamp(rawPx, CHAT_MIN_WIDTH, CHAT_MAX_WIDTH), chatCollapsed: false });
    },
    [persist]
  );
  const commitResizeRail = useCallback(
    (rawPx: number) => {
      if (rawPx < RAIL_COLLAPSE_AT) {
        persist({ ...stateRef.current, railCollapsed: true });
        return;
      }
      persist({ ...stateRef.current, railWidth: clamp(rawPx, RAIL_MIN_WIDTH, RAIL_MAX_WIDTH), railCollapsed: false });
    },
    [persist]
  );

  const collapseChat = useCallback(() => persist({ ...stateRef.current, chatCollapsed: true }), [persist]);
  const expandChat = useCallback(() => persist({ ...stateRef.current, chatCollapsed: false }), [persist]);
  const collapseRail = useCallback(() => persist({ ...stateRef.current, railCollapsed: true }), [persist]);
  const expandRail = useCallback(() => persist({ ...stateRef.current, railCollapsed: false }), [persist]);

  return {
    hydrated,
    isLgUp,
    chatWidth: state.chatWidth,
    railWidth: state.railWidth,
    chatCollapsed: state.chatCollapsed,
    railCollapsed: state.railCollapsed,
    liveResizeChat,
    liveResizeRail,
    commitResizeChat,
    commitResizeRail,
    collapseChat,
    expandChat,
    collapseRail,
    expandRail,
  };
}
