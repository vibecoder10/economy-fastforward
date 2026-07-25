"use client";

import { useDirector } from "./DirectorContext";
import { DirectorHome } from "./DirectorHome";
import { CanvasHeader } from "./CanvasHeader";
import { CanvasStage } from "./CanvasStage";
import { RightRail } from "./RightRail";

/**
 * Top-level Director surface (Chunk 1.A, header/rail wired in Chunk 1.E).
 * Renders the home screen full width when no video is selected, otherwise
 * the full app shell described in storyengine/tasks/director-mockup/
 * index.html (`#app`: `.topbar` + `.cols` > `.chat` + `.stage` + `.rail`,
 * ~L746-1320).
 *
 * The mockup's `.chat` column is a fixed 412px and its `.stage` fills the
 * rest with a `.rail` on the far side. Chunk 1.A's own spec asks for a
 * flexible `min-w-[380px] max-w-[460px] w-[38%]` chat column instead, so
 * this file follows the chunk brief over the mockup's literal pixel width.
 */
export function DirectorSurface() {
  const { selectedVideoId } = useDirector();

  if (selectedVideoId === null) {
    return <DirectorHome />;
  }

  return (
    <div className="flex h-full w-full flex-col">
      <CanvasHeader videoId={selectedVideoId} />

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
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

        {/* Canvas column — the altitude-routed stage (Shot / Scene / Timeline). */}
        <div className="flex min-w-0 flex-1 flex-col bg-void">
          <CanvasStage videoId={selectedVideoId} />
        </div>

        {/* Right rail — Media / Voice / Music / Cast / Environments. */}
        <RightRail videoId={selectedVideoId} />
      </div>
    </div>
  );
}
