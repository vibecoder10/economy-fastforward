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
  onLiveResize,
  onCommitResize,
  onCollapse,
}: {
  side: Side;
  label: string;
  measureRef: React.RefObject<HTMLElement | null>;
  min: number;
  max: number;
  onLiveResize: (px: number) => void;
  onCommitResize: (px: number) => void;
  onCollapse: () => void;
}) {
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);

  const widthFromDelta = (deltaX: number, startWidth: number) =>
    side === "left" ? startWidth + deltaX : startWidth - deltaX;

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!measureRef.current) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { startX: e.clientX, startWidth: measureRef.current.getBoundingClientRect().width };
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    onLiveResize(widthFromDelta(e.clientX - drag.current.startX, drag.current.startWidth));
  };

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    onCommitResize(widthFromDelta(e.clientX - drag.current.startX, drag.current.startWidth));
    drag.current = null;
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
    }
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${label} panel`}
      aria-valuemin={min}
      aria-valuemax={max}
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
        type="button"
        tabIndex={-1}
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => {
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
