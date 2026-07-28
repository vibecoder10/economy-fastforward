"use client";

import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

/**
 * Harvested out of ScenesWorkspaceTab.tsx, where it was already named
 * `BoardLightbox` (DIRECTOR-CHAT-PLAN.md Task 0.2 calls it a rename from
 * `MediaLightbox` — the branch this plan was written against had it under
 * that name; on this branch it had already been renamed, so this is a pure
 * move + export, no rename needed).
 *
 * Full-screen in-app board viewer. Esc or backdrop closes; ←/→ move between
 * the scene's boards. Exists because the raw storage URL downloads instead of
 * displaying — the user should never leave the page to look at a board.
 *
 * CONTRACT: this renders a bare `<img src={item.url}>` with no URL
 * transform. The caller MUST pass a URL that has already been run through
 * `toDisplayImageUrl` (see `@/lib/utils`) — this component does not do it.
 *
 * Portals to `document.body` (found wiring this into the chat co-pilot
 * panel's result cards, ChatResultCards.tsx): the Director canvas layout
 * (CanvasStage.tsx) puts a framer-motion `transform` on an ancestor of that
 * panel, which per the CSS spec makes that ancestor the containing block for
 * `position: fixed` descendants — without the portal this viewer rendered
 * clipped to the narrow chat column instead of covering the screen. A portal
 * is a no-op for ScenesWorkspaceTab.tsx's existing usage (no such ancestor
 * there), so this is safe for both call sites.
 */
export function BoardLightbox({ items, index, onNavigate, onClose }: {
  items: { url: string; label: string }[];
  index: number;
  onNavigate: (i: number) => void;
  onClose: () => void;
}) {
  const item = items[Math.min(index, items.length - 1)];
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" && index < items.length - 1) onNavigate(index + 1);
      else if (e.key === "ArrowLeft" && index > 0) onNavigate(index - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, items.length, onNavigate, onClose]);
  if (!item) return null;
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center"
      style={{ background: "rgba(0,0,0,0.92)" }}
      onClick={onClose}
    >
      <button
        onClick={onClose}
        title="Close (Esc)"
        className="absolute top-4 right-4 w-9 h-9 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
        style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>
        <X size={18} />
      </button>
      {index > 0 && (
        <button
          onClick={(e) => { e.stopPropagation(); onNavigate(index - 1); }}
          title="Previous board (←)"
          className="absolute left-4 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full flex items-center justify-center text-xl transition-colors hover:brightness-125"
          style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>
          ‹
        </button>
      )}
      {index < items.length - 1 && (
        <button
          onClick={(e) => { e.stopPropagation(); onNavigate(index + 1); }}
          title="Next board (→)"
          className="absolute right-4 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full flex items-center justify-center text-xl transition-colors hover:brightness-125"
          style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>
          ›
        </button>
      )}
      <img
        src={item.url}
        alt={item.label}
        onClick={(e) => e.stopPropagation()}
        className="max-w-[94vw] max-h-[88vh] object-contain rounded-lg"
      />
      <p className="mt-3 text-sm font-mono" style={{ color: "rgba(255,255,255,0.75)" }}>
        {item.label}{items.length > 1 ? ` · ${index + 1}/${items.length}` : ""}
      </p>
    </div>,
    document.body,
  );
}
