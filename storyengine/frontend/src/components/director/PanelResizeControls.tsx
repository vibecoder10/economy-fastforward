"use client";

import { useRef } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

type Side = "left" | "right";

/**
 * Draggable seam between two Director surface columns (DirectorSurface.tsx).
 * `side` says which column this handle belongs to: "left" for the chat
 * column (dragging the seam right makes it wider), "right" for the rail
 * column (dragging the seam right makes it narrower). Only rendered when
 * that column is visible — collapsed columns show a `CollapsedPanelStub`
 * instead, which carries its own "show" control.
 *
 * Hidden below `lg` (`hidden ... lg:flex`) — matches DirectorSurface's
 * existing `flex-col lg:flex-row` stacking; resizing a stacked layout is
 * meaningless, so the handle (and its hit area) simply doesn't exist there.
 *
 * Pointer events (not mouse-only) so trackpad/touch drags work. Width is
 * always read fresh off `measureRef` at drag/keydown start rather than
 * threaded through as a prop — that works identically whether the column's
 * current width comes from a Tailwind default (%, fixed px) or a previous
 * drag's inline style, with no separate "what's the default width" case.
 */
export function PanelDivider({
  side,
  label,
  measureRef,
  min,
  max,
  valueNow,
  onLiveResize,
  onCommitResize,
  onCollapse,
}: {
  side: Side;
  label: string;
  measureRef: React.RefObject<HTMLElement | null>;
  min: number;
  max: number;
  /** Current column width in px, kept live by a ResizeObserver in
   * DirectorSurface.tsx — drives `aria-valuenow` so it tracks every source
   * of a width change (drag, keyboard, or the original CSS-driven default),
   * not just this component's own drag state. */
  valueNow: number;
  onLiveResize: (px: number) => void;
  onCommitResize: (px: number) => void;
  onCollapse: () => void;
}) {
  const drag = useRef<{ startX: number; startY: number; startWidth: number; startedOnButton: boolean } | null>(
    null
  );
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Below this much pointer movement (in px, any direction), a press+release
  // counts as a click, not a drag. Real fix for a bug found in review: the
  // "Hide" button sits dead-center on the handle — exactly where a user
  // naturally grabs to drag — so its own onPointerDown used to call
  // stopPropagation() to keep clicks from starting a drag. That swallowed
  // EVERY real-mouse drag that began anywhere near the button (confirmed via
  // Playwright: a real press-move-release drag never moved the divider).
  // Removing that stopPropagation fixes dragging, but pointer capture
  // (below) is set on THIS element once a press starts, and per this
  // engine's behavior that also suppresses the button's native "click"
  // synthesis for the rest of that press (confirmed via Playwright: a real
  // click on the button stopped collapsing once capture moved to the
  // parent). So click-vs-drag is decided here, in one place, instead of
  // splitting it between this element and the button's own handlers.
  const CLICK_MOVE_THRESHOLD = 4;

  const widthFromDelta = (deltaX: number, startWidth: number) =>
    side === "left" ? startWidth + deltaX : startWidth - deltaX;

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!measureRef.current) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = {
      startX: e.clientX,
      startY: e.clientY,
      startWidth: measureRef.current.getBoundingClientRect().width,
      startedOnButton: !!buttonRef.current?.contains(e.target as Node),
    };
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    onLiveResize(widthFromDelta(e.clientX - drag.current.startX, drag.current.startWidth));
  };

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const { startX, startY, startWidth, startedOnButton } = drag.current;
    const moved = Math.hypot(e.clientX - startX, e.clientY - startY);
    drag.current = null;
    if (moved < CLICK_MOVE_THRESHOLD && startedOnButton) {
      onCollapse();
      return;
    }
    onCommitResize(widthFromDelta(e.clientX - startX, startWidth));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!measureRef.current) return;
    const current = measureRef.current.getBoundingClientRect().width;
    const step = e.shiftKey ? 48 : 16;
    const widenKey = side === "left" ? "ArrowRight" : "ArrowLeft";
    const narrowKey = side === "left" ? "ArrowLeft" : "ArrowRight";
    if (e.key === widenKey) {
      onCommitResize(current + step);
      e.preventDefault();
    } else if (e.key === narrowKey) {
      onCommitResize(current - step);
      e.preventDefault();
    } else if (e.key === "Home") {
      onCommitResize(min);
      e.preventDefault();
    } else if (e.key === "End") {
      onCommitResize(max);
      e.preventDefault();
    } else if (e.key === "Enter") {
      // The button is `tabIndex={-1}` (this separator is the one Tab stop
      // for the whole handle), so a pure-keyboard user has no way to reach
      // it directly — give the same collapse action a keyboard path here.
      onCollapse();
      e.preventDefault();
    }
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${label} panel`}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={Math.round(valueNow)}
      tabIndex={0}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={handleKeyDown}
      className="group relative hidden w-3 flex-none cursor-col-resize touch-none select-none items-stretch lg:flex focus:outline-none"
    >
      <div className="pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-line-soft transition-colors group-hover:bg-turquoise/50 group-focus-visible:bg-turquoise" />
      <button
        ref={buttonRef}
        type="button"
        tabIndex={-1}
        onClick={(e) => {
          // Redundant fallback only — the real path is endDrag() above,
          // since pointer capture on the separator suppresses this engine's
          // native click synthesis for the rest of an active press. Harmless
          // to keep: if some environment DOES fire it, it's the same action.
          e.stopPropagation();
          onCollapse();
        }}
        title={`Hide ${label}`}
        aria-label={`Hide ${label}`}
        aria-expanded="true"
        className="pointer-events-auto absolute left-1/2 top-1/2 z-10 flex h-7 w-4 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-[5px] border border-line-soft bg-surface text-faint opacity-0 shadow-[0_2px_10px_rgba(0,0,0,0.35)] transition-opacity hover:text-ink group-hover:opacity-100 group-focus-visible:opacity-100"
      >
        {side === "left" ? <ChevronLeft size={11} /> : <ChevronRight size={11} />}
      </button>
    </div>
  );
}

/**
 * What a collapsed column becomes: a thin, always-visible strip with the
 * one control that brings it back. Hidden below `lg` for the same reason as
 * the divider — collapse never takes visual effect on a stacked layout, so
 * there's no dangling "column you can't get back" on a narrow viewport.
 */
export function CollapsedPanelStub({
  side,
  label,
  onExpand,
}: {
  side: Side;
  label: string;
  onExpand: () => void;
}) {
  return (
    <div
      className={`hidden w-6 flex-none flex-col items-center gap-2 bg-surface py-2.5 lg:flex ${
        side === "left" ? "border-r border-line" : "border-l border-line"
      }`}
    >
      <button
        type="button"
        onClick={onExpand}
        title={`Show ${label}`}
        aria-label={`Show ${label}`}
        aria-expanded="false"
        className="flex h-6 w-6 flex-none items-center justify-center rounded-[6px] text-faint transition-colors hover:bg-raise hover:text-ink"
      >
        {side === "left" ? <ChevronRight size={13} /> : <ChevronLeft size={13} />}
      </button>
      <span className="text-[9.5px] font-semibold tracking-wide text-faint [writing-mode:vertical-rl]">{label}</span>
    </div>
  );
}
