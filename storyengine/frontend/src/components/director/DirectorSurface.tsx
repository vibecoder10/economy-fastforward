"use client";

import { useDirector } from "./DirectorContext";
import { DirectorHome } from "./DirectorHome";
import { CanvasEmptyState } from "./CanvasEmptyState";

/**
 * Top-level Director surface (Chunk 1.A). Renders the home screen full
 * width when no video is selected, otherwise the two-column chat/canvas
 * layout described in storyengine/tasks/director-mockup/index.html
 * (`#app` > `.cols` > `.chat` + `.stage`, ~L822-894).
 *
 * The mockup's `.chat` column is a fixed 412px and its `.stage` fills the
 * rest with a `.rail` on the far side. Chunk 1.A's own spec asks for a
 * flexible `min-w-[380px] max-w-[460px] w-[38%]` chat column instead (no
 * right rail yet — that's Chunk 1.E), so this file follows the chunk brief
 * over the mockup's literal pixel width.
 */
export function DirectorSurface() {
  const { selectedVideoId } = useDirector();

  if (selectedVideoId === null) {
    return <DirectorHome />;
  }

  return (
    <div className="flex h-full w-full flex-col lg:flex-row">
      {/* Chat column — ChatCore is being edited by another worker in this
          same pass (frontend/src/components/chat/ChatCore.tsx) and must not
          be imported or rendered here yet. This placeholder is sized
          exactly like the real chat column will be, so the layout is real
          and screenshot-able ahead of that wiring. */}
      <div
        className="flex min-w-[380px] max-w-[460px] w-full flex-none flex-col border-b border-edge bg-surface lg:w-[38%] lg:border-b-0 lg:border-r"
        data-director-chat-placeholder="true"
      >
        <div className="flex h-full items-center justify-center p-6">
          <p className="text-center text-sm text-faint">
            Chat column placeholder — ChatCore renders here (owned by another chunk).
          </p>
        </div>
      </div>

      {/* Canvas column — fills the remaining width. Chunk 1.E adds the
          stage bar (tabs, Lock-as-style, cost dial) and the right rail
          (Media / Voice / Music / Cast / Environments) around this. */}
      <div className="flex min-w-0 flex-1 flex-col bg-void">
        <CanvasEmptyState />
      </div>
    </div>
  );
}
