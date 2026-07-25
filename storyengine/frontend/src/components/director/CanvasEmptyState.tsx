"use client";

import { Clapperboard } from "lucide-react";

/**
 * Canvas-side empty state for the Director surface (Chunk 1.A). Shown while
 * a video has nothing to render yet — a ghost timeline reads the destination
 * (where scenes/shots will eventually stack up) before any content exists.
 * Chunk 1.E replaces the stage bar/rail above and around this; this
 * component only owns the empty canvas body itself.
 */
export function CanvasEmptyState() {
  return (
    <div className="relative flex h-full w-full flex-col items-center justify-center overflow-hidden bg-void px-6">
      {/* Ghost timeline — decorative, non-interactive, sits behind the
          message so the eventual scene/shot layout reads before anything
          has been generated. Mirrors the shape of the mockup's `.scene` /
          `.shot` rows (director-mockup/index.html ~L331-345) at low opacity. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-4 opacity-[0.08]"
      >
        {[0, 1, 2].map((row) => (
          <div key={row} className="flex gap-3">
            {[0, 1, 2, 3, 4].map((col) => (
              <div
                key={col}
                className="h-24 w-40 flex-none rounded-card-sm border border-line-soft bg-raise"
              />
            ))}
          </div>
        ))}
      </div>

      {/* Foreground message */}
      <div className="relative z-10 flex flex-col items-center gap-4 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-card border border-line-soft bg-surface">
          <Clapperboard className="h-6 w-6 text-faint" strokeWidth={1.5} />
        </div>
        <p className="text-sm font-medium text-dim">Your video will land here.</p>
      </div>
    </div>
  );
}
