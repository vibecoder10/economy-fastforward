"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Sidebar collapsed/expanded/hidden state — shared between Sidebar.tsx
 * (renders the icon-rail toggle at the bottom and the full-hide toggle at
 * the top) and AuthenticatedShell.tsx (whose <main> needs the real rail
 * width so collapsing/hiding actually reclaims content space, not just
 * shrinks the rail). Lives in ONE hook instance in AuthenticatedShell and is
 * passed down to Sidebar as controlled props — a second independent
 * instance would each read the same localStorage keys at mount but never
 * see the other's later writes (same-tab `localStorage` writes don't
 * retrigger React renders), so collapsing/hiding would still leave a dead
 * gutter.
 *
 * Two independent booleans, not one three-state enum, because they're two
 * different axes: `collapsed` is the icon-rail density (still a visible,
 * usable panel) and `hidden` is "no panel at all" (D3-48). `hidden`
 * supersedes `collapsed` purely at render time in Sidebar/AuthenticatedShell
 * — a hidden+collapsed combination is valid state (you can toggle rail
 * density, hide, and unhide back into whichever rail density you left it
 * in) without needing a third enum value.
 *
 * Follows the existing `se_*` localStorage + hydration-gate convention (see
 * components/director/usePanelLayout.ts, ChatCore.tsx's chat-id keys):
 * default (expanded, visible) matches today's always-expanded server-rendered
 * markup exactly, so first paint never mismatches between server and
 * client — the real saved value loads in a client-only effect and the
 * layout animates to it (CSS `transition`), it never mismatches.
 */
const STORAGE_KEY = "se_sidebar_collapsed_v1";
const HIDDEN_STORAGE_KEY = "se_sidebar_hidden_v1";

// Tailwind `w-60` / `md:ml-60` and `w-16` — keep in sync with sidebar.tsx and
// AuthenticatedShell.tsx's className strings (plain numbers so both a CSS
// class name and a pixel value, if ever needed, can be derived from one
// source instead of retyping "240"/"64" in multiple files).
export const SIDEBAR_WIDTH_EXPANDED = 240;
export const SIDEBAR_WIDTH_COLLAPSED = 64;

export function useSidebarCollapsed() {
  const [collapsed, setCollapsedState] = useState(false);
  const [hidden, setHiddenState] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      setCollapsedState(window.localStorage.getItem(STORAGE_KEY) === "1");
      setHiddenState(window.localStorage.getItem(HIDDEN_STORAGE_KEY) === "1");
    } catch {
      // Private mode / storage unavailable — keep the defaults (expanded, visible).
    }
    setHydrated(true);
  }, []);

  const setCollapsed = useCallback((next: boolean) => {
    setCollapsedState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch {
      // Best-effort only — a full/blocked localStorage should never crash
      // the app, it just won't remember next time.
    }
  }, []);

  const setHidden = useCallback((next: boolean) => {
    setHiddenState(next);
    try {
      window.localStorage.setItem(HIDDEN_STORAGE_KEY, next ? "1" : "0");
    } catch {
      // Best-effort only — same as setCollapsed above.
    }
  }, []);

  return { collapsed, setCollapsed, hidden, setHidden, hydrated };
}
