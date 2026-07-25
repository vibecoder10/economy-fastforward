"use client";

import { useDirector } from "./DirectorContext";
import { DirectorHome } from "./DirectorHome";
import { CanvasHeader } from "./CanvasHeader";
import { CanvasStage } from "./CanvasStage";
import { RightRail } from "./RightRail";
import { ChatCore } from "@/components/chat/ChatCore";

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
  const { selectedVideoId, setSelectedVideoId } = useDirector();

  if (selectedVideoId === null) {
    return <DirectorHome />;
  }

  return (
    <div className="flex h-full w-full flex-col">
      <CanvasHeader videoId={selectedVideoId} />

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* Chat column — the shared chat engine (DIRECTOR-CHAT-PLAN.md Task 1.2).
            Mounted `docked={false}` (its default) — the "undocked"/home flavor,
            NOT the old in-pipeline "dock" mode — on purpose:
              - `docked={true}` would only ever fire `onVideoCreated` in a world
                where a video ALREADY exists (the callback is gated by `!docked`
                in ChatCore's turn()), so a "make me another video" request typed
                from inside an open video's canvas would never open its canvas —
                the whole point of wiring onVideoCreated here.
              - `activeVideoId` (not `videoId`) is what feeds `video_id` on this
                path (`docked ? videoId : req.video_id ?? activeVideoId ?? null`)
                — passing `videoId` instead would only matter under docked=true.
            `selectedVideoId` is narrowed to a real string here (the `null` case
            returns <DirectorHome /> above), so `activeVideoId` is always the
            real open video, never a stale fallback — never re-derived from
            anything else. `uiContext` is left unset: widening it to carry
            altitude/scene/rail state is its own future task
            (DIRECTOR-CHAT-PLAN.md line ~448), out of this chunk's scope. */}
        {/* `relative` + `transform-gpu` make this column a CSS containing
            block, so ChatCore's `fixed bottom-0 left-0 right-0 md:left-60`
            composer (ChatCore.tsx ~L810, undocked/home layout) resolves
            against THIS column instead of the viewport — it would otherwise
            span the full app width, on top of the canvas. `transform` (any
            non-none value, `translateZ(0)` here) is what the CSS spec keys
            the fixed-positioning containing block off of; no ChatCore change
            needed. Second-order effect (checked, see DirectorSurface.tsx
            history / ChatCore.tsx ChatHistoryMenu): ChatCore's only other
            `fixed` element is `fixed inset-0 z-10` (~L1062), the click-outside
            backdrop behind the chat-history dropdown — it now also resolves
            against this column, so clicking the canvas/rail while that
            dropdown is open no longer auto-closes it (clicking anywhere
            inside the column, or picking an item, still does). Scoped,
            low-severity, and unrelated to the composer-escape bug this fixes. */}
        <div
          className="relative flex min-w-[380px] max-w-[460px] w-full flex-none flex-col overflow-y-auto border-b border-edge bg-surface transform-gpu lg:w-[38%] lg:border-b-0 lg:border-r"
          data-director-chat-column="true"
        >
          <ChatCore
            docked={false}
            activeVideoId={selectedVideoId}
            onVideoCreated={(id) => setSelectedVideoId(id)}
          />
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
