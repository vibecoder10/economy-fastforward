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
// the canvas's own floor (CANVAS_MIN_WIDTH below) still leaves the canvas
// close to usable on a real, sidebar-EXPANDED 1280px-wide window — the
// tightest realistic case, since the app sidebar reserves 240px when
// expanded (AuthenticatedShell.tsx, commit 692212db). This alone does NOT
// guarantee the row fits, though — see `fitWidths` below, added after a live
// repro (Playwright, 2026-07-27) showed even the plain, never-dragged
// DEFAULT layout overflows that exact 1280px/sidebar-expanded case (the
// media rail's own tabs rendered clipped off the right edge). CHAT_MAX_WIDTH
// stays the drag ceiling; `fitWidths` is what keeps the RENDERED width from
// ever exceeding what's actually available.
export const CHAT_MAX_WIDTH = 480;
const CHAT_COLLAPSE_AT = 180; // drag-release below this snaps the chat column closed

export const RAIL_MIN_WIDTH = 240;
export const RAIL_MAX_WIDTH = 420;
const RAIL_COLLAPSE_AT = 170; // drag-release below this snaps the rail column closed

// The chat column's plain (never-customized) responsive default —
// DirectorSurface.tsx's `lg:min-w-[380px] lg:max-w-[460px] lg:w-[38%]`,
// mirrored here as numbers so the "no custom width yet" case can be run
// through the SAME fit-clamp as a real dragged width (see `fitWidths`).
// Deliberately narrower than CHAT_MIN_WIDTH/CHAT_MAX_WIDTH — those are the
// wider range a drag is allowed to reach; this is only the passive default.
const CHAT_DEFAULT_MIN = 380;
const CHAT_DEFAULT_MAX = 460;
const CHAT_DEFAULT_PERCENT = 0.38;

// The rail column's plain (never-customized) default — RightRail.tsx's
// `w-[340px]`, mirrored the same way as CHAT_DEFAULT_*.
const RAIL_DEFAULT_WIDTH = 340;

// Row-fit constants — the OTHER pieces DirectorSurface arranges alongside
// chat/rail in the same row, needed to know how much width chat+rail
// actually have left to share. Keep these in sync with the real markup:
//   - DIVIDER_WIDTH: PanelDivider's `w-3` (PanelResizeControls.tsx)
//   - STUB_WIDTH: CollapsedPanelStub's `w-6` (PanelResizeControls.tsx)
//   - CANVAS_MIN_WIDTH: the canvas column's `min-w-[320px]` (DirectorSurface.tsx)
// A mismatch here only makes the fit math a little conservative or
// generous — both constants are on the "reserved" side of the budget, so a
// drift can never reintroduce the overflow this file exists to prevent.
const DIVIDER_WIDTH = 12;
const STUB_WIDTH = 24;
export const CANVAS_MIN_WIDTH = 320;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * Shrinks a proposed chat/rail width pair down to whatever ACTUALLY fits in
 * `rowWidth` — the live measured width of the row that holds
 * chat + divider + canvas + divider + rail — scaling both down
 * proportionally (never below either's own MIN) rather than letting one
 * panel starve the other. This is the fix for the horizontal-scroll bug:
 * found live (Playwright, 2026-07-27) that even the plain DEFAULT layout —
 * chat at its ~38% default, rail at its fixed 340px default, nobody having
 * ever dragged anything — already adds up to more than the ~1040px actually
 * left in a 1280px-wide window next to a 240px EXPANDED sidebar (395 + 340 +
 * 24px of dividers + the canvas's own 320px floor = 1079 > 1040). A user who
 * had also dragged chat/rail wider (within their already-allowed max) only
 * makes the gap bigger. Every caller of `chatWidth`/`railWidth` below gets
 * the fitted number, so there is no code path that can render a row wider
 * than `rowWidth` once it's known.
 *
 * A collapsed column becomes a fixed CollapsedPanelStub (24px) with no
 * divider of its own and contributes nothing to the squeeze — `chatVisible`/
 * `railVisible` say which dividers/stubs are actually in the row right now
 * so the reserved-width math matches what's really rendered.
 */
function fitWidths(
  chatWidth: number,
  railWidth: number,
  rowWidth: number | null,
  chatVisible: boolean,
  railVisible: boolean
): { chatWidth: number; railWidth: number } {
  if (rowWidth == null) return { chatWidth, railWidth };

  const reserved =
    CANVAS_MIN_WIDTH +
    (chatVisible ? DIVIDER_WIDTH : STUB_WIDTH) +
    (railVisible ? DIVIDER_WIDTH : STUB_WIDTH);
  const budget = rowWidth - reserved;

  if (!chatVisible && !railVisible) return { chatWidth, railWidth };
  if (!chatVisible) {
    return { chatWidth, railWidth: clamp(railWidth, RAIL_MIN_WIDTH, Math.max(RAIL_MIN_WIDTH, budget)) };
  }
  if (!railVisible) {
    return { chatWidth: clamp(chatWidth, CHAT_MIN_WIDTH, Math.max(CHAT_MIN_WIDTH, budget)), railWidth };
  }

  if (budget <= 0) {
    // Viewport so tight not even both MINIMUMS fit — floor both rather than
    // run a scale computation on a non-positive budget. Below where `lg:`
    // would stack the columns anyway in any realistic window, so this is a
    // rarely-hit floor, not the common path.
    return { chatWidth: CHAT_MIN_WIDTH, railWidth: RAIL_MIN_WIDTH };
  }

  const total = chatWidth + railWidth;
  if (total <= budget) return { chatWidth, railWidth };

  const scale = budget / total;
  const scaledChat = Math.max(CHAT_MIN_WIDTH, Math.floor(chatWidth * scale));
  const scaledRail = Math.max(RAIL_MIN_WIDTH, Math.floor(railWidth * scale));
  return { chatWidth: scaledChat, railWidth: scaledRail };
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
 *
 * `rowWidth` (reported by DirectorSurface via `reportRowWidth`, from a
 * ResizeObserver on the row that actually holds chat+canvas+rail) is what
 * lets `chatWidth`/`railWidth` below re-clamp against whatever space is
 * REALLY available right now — on first load, on a window resize, AND on a
 * sidebar collapse/expand (that changes `main`'s margin, which changes this
 * row's width, which the same ResizeObserver picks up — no separate
 * listener needed for any of the three).
 */
export function usePanelLayout() {
  const [hydrated, setHydrated] = useState(false);
  const [isLgUp, setIsLgUp] = useState(true);
  const [state, setState] = useState<PanelLayoutState>(DEFAULT_STATE);
  const [rowWidth, setRowWidth] = useState<number | null>(null);
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

  const reportRowWidth = useCallback((px: number) => {
    setRowWidth((prev) => (prev != null && Math.abs(prev - px) < 1 ? prev : px));
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

  // "Intent" widths — the stored custom value if the creator ever dragged
  // one, else the same default this column renders via plain CSS today
  // (`w-[38%]`/`w-[340px]`), computed as a real px number so the untouched
  // DEFAULT case goes through the exact same fit-clamp as a customized one
  // (the default case overflows too — see `fitWidths`'s own comment). Only
  // computed once `rowWidth` is known; before that this whole expression is
  // moot because `fitWidths` short-circuits on `rowWidth == null` below.
  const chatIntent =
    state.chatWidth ??
    (rowWidth != null ? clamp(rowWidth * CHAT_DEFAULT_PERCENT, CHAT_DEFAULT_MIN, CHAT_DEFAULT_MAX) : CHAT_DEFAULT_MIN);
  const railIntent = state.railWidth ?? RAIL_DEFAULT_WIDTH;

  const fitted = fitWidths(chatIntent, railIntent, rowWidth, !state.chatCollapsed, !state.railCollapsed);

  return {
    hydrated,
    isLgUp,
    // Before the row's width is measured: unchanged contract (null = "render
    // the plain default CSS class, not a custom width"). Once measured:
    // ALWAYS a fitted pixel number — whether the creator customized this
    // column or not — so the row can never render wider than what's really
    // available. DirectorSurface's existing `chatWidthPx != null` branching
    // needs no change; it just starts receiving a number sooner than before.
    chatWidth: rowWidth != null ? fitted.chatWidth : state.chatWidth,
    railWidth: rowWidth != null ? fitted.railWidth : state.railWidth,
    chatCollapsed: state.chatCollapsed,
    railCollapsed: state.railCollapsed,
    reportRowWidth,
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
