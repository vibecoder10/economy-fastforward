"use client";

import { useCallback, useEffect } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useDirector } from "./DirectorContext";

/**
 * Chunk D3-46: the right rail's Media/Storyboards/Images/Videos thumbnails
 * were dead — clicking one did nothing (confirmed live on prod: no handler,
 * no modal, no console error). This is the fix: a self-contained overlay
 * mounted inside DirectorSurface's canvas column, over `<CanvasStage>`, NOT
 * wired through `DirectorContext.focusedShotId` — see that field's doc
 * comment and `LightboxState`'s in DirectorContext.tsx for why a separate
 * field exists instead. Deliberately does not touch SceneAltitudeView or
 * any other part of the shot-altitude system — mounted as its own layer, on
 * its own state, so this stays a self-contained addition rather than a
 * refactor of the canvas.
 *
 * Renders nothing when `lightbox` is null (the common case) — mount this
 * unconditionally in the canvas column and it's a no-op until RightRail's
 * MediaPanel sets state via a thumbnail click.
 */
export function MediaLightbox() {
  const { lightbox, setLightbox } = useDirector();
  const items = lightbox?.items ?? [];
  const index = lightbox?.index ?? 0;
  const item = items[index];

  const close = useCallback(() => setLightbox(null), [setLightbox]);

  const step = useCallback(
    (delta: number) => {
      if (items.length === 0) return;
      const next = (index + delta + items.length) % items.length;
      setLightbox({ items, index: next });
    },
    [items, index, setLightbox]
  );

  // Esc to close, arrow keys to step siblings — only listens while actually
  // open (the `lightbox` guard inside, not a conditional hook call: this
  // effect always runs, it just no-ops when there's nothing to listen for).
  useEffect(() => {
    if (!lightbox) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightbox, close, step]);

  if (!lightbox || !item) return null;

  return (
    <div
      className="absolute inset-0 z-30 flex items-center justify-center bg-black/85 p-6 backdrop-blur-sm"
      onClick={close}
      role="dialog"
      aria-modal="true"
      aria-label={item.label}
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          close();
        }}
        aria-label="Close"
        className="absolute right-4 top-4 flex h-9 w-9 items-center justify-center rounded-full bg-black/60 text-white/80 transition-colors hover:bg-black/80 hover:text-white"
      >
        <X size={18} />
      </button>

      {items.length > 1 && (
        <>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              step(-1);
            }}
            aria-label="Previous"
            className="absolute left-4 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/60 text-white/80 transition-colors hover:bg-black/80 hover:text-white"
          >
            <ChevronLeft size={20} />
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              step(1);
            }}
            aria-label="Next"
            className="absolute right-4 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/60 text-white/80 transition-colors hover:bg-black/80 hover:text-white"
          >
            <ChevronRight size={20} />
          </button>
        </>
      )}

      {/* Stops the backdrop's onClick (which closes) from firing when the
          click actually landed on the media/label itself. */}
      <div className="flex max-h-full max-w-full flex-col items-center gap-3" onClick={(e) => e.stopPropagation()}>
        {item.kind === "video" ? (
          <video
            key={item.key}
            src={item.url}
            controls
            autoPlay
            playsInline
            className="max-h-[75vh] max-w-full rounded-[10px] bg-black"
          />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={item.key}
            src={item.url}
            alt={item.label}
            className="max-h-[75vh] max-w-full rounded-[10px] object-contain"
          />
        )}
        <div className="rounded-full bg-black/60 px-3 py-1 text-[12px] font-medium text-white/90">
          {item.label}
          {items.length > 1 ? (
            <span className="text-white/50">
              {" "}
              · {index + 1}/{items.length}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
