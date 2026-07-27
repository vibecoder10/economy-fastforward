"use client";

import { useEffect, useRef, useState } from "react";
import { useDirector } from "./DirectorContext";
import { DirectorHome } from "./DirectorHome";
import { CanvasHeader } from "./CanvasHeader";
import { CanvasStage } from "./CanvasStage";
import { RightRail } from "./RightRail";
import { ChatCore } from "@/components/chat/ChatCore";
import { CollapsedPanelStub, PanelDivider } from "./PanelResizeControls";
import { CHAT_MAX_WIDTH, CHAT_MIN_WIDTH, RAIL_MAX_WIDTH, RAIL_MIN_WIDTH, usePanelLayout } from "./usePanelLayout";

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
  const { selectedVideoId, setSelectedVideoId, pendingInitialMessage, setPendingInitialMessage } = useDirector();
  const chatColumnRef = useRef<HTMLDivElement>(null);
  const railColumnRef = useRef<HTMLDivElement>(null);
  const rowRef = useRef<HTMLDivElement>(null);
  const layout = usePanelLayout();

  // Feeds usePanelLayout's row-fit clamp (usePanelLayout.ts `fitWidths`) the
  // row's REAL live width — the space chat+dividers+canvas+rail actually
  // have to share, next to whatever the sidebar is doing right now. A plain
  // window-resize listener would miss a sidebar collapse/expand (that only
  // changes `main`'s margin, not the window size); this ResizeObserver
  // catches both, since either one changes this element's own rendered
  // width. Root cause this exists for: a live repro (Playwright,
  // 2026-07-27) showed the untouched DEFAULT layout (chat ~38%, rail fixed
  // 340px, canvas's 320px floor, two 12px dividers) already adds up to more
  // than the ~1040px left in a 1280px window next to a 240px EXPANDED
  // sidebar — the media rail rendered with its own tabs clipped off the
  // right edge, no drag required to trigger it.
  //
  // No dependency array (matches the chat/rail measurement effects below,
  // and for the same reason): DirectorSurface itself mounts once and stays
  // mounted across the DirectorHome -> room transition (only
  // `selectedVideoId` changes), so `rowRef.current` is still null on the
  // very first run of an effect gated by `[]` — the row div doesn't exist
  // until a video is selected. Re-running this effect every render is what
  // lets it pick up the ref the moment the row actually mounts.
  useEffect(() => {
    const el = rowRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => layout.reportRowWidth(el.getBoundingClientRect().width));
    ro.observe(el);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  });

  // Consume-once: the DirectorHome entry box stashes the creator's typed
  // sentence here right before setSelectedVideoId(newVideoId). ChatCore's own
  // mount effect reads the `initialMessage` prop synchronously (before this
  // effect's setState commits), so clearing it here the same tick is safe —
  // it only prevents a LATER video switch (e.g. via "Recent videos", which
  // never sets this field) from replaying a stale pitch into an unrelated
  // conversation.
  useEffect(() => {
    if (pendingInitialMessage) setPendingInitialMessage(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedVideoId]);

  // Live-measured widths, kept in sync with a ResizeObserver rather than
  // read once — this is what feeds `aria-valuenow` on each divider, and it
  // stays correct regardless of WHY the width changed (a drag, a keyboard
  // nudge, or just the original CSS-driven default before any interaction).
  const [chatMeasuredWidth, setChatMeasuredWidth] = useState<number | null>(null);
  const [railMeasuredWidth, setRailMeasuredWidth] = useState<number | null>(null);

  useEffect(() => {
    const el = chatColumnRef.current;
    if (!el) return;
    // Re-measure via getBoundingClientRect (border-box), NOT the observer
    // entry's own contentRect (excludes border) — PanelDivider measures the
    // same ref the same way for its drag math, so aria-valuenow always
    // agrees with the number that actually drove the resize.
    const ro = new ResizeObserver(() => setChatMeasuredWidth(el.getBoundingClientRect().width));
    ro.observe(el);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  });

  useEffect(() => {
    const el = railColumnRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setRailMeasuredWidth(el.getBoundingClientRect().width));
    ro.observe(el);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  });

  if (selectedVideoId === null) {
    return <DirectorHome />;
  }

  // Only apply a custom width once hydrated AND at `lg`+ — before hydration
  // or below `lg`, render exactly the original classes (no inline style),
  // so a fresh visitor and a narrow viewport both see today's layout.
  const chatWidthPx = layout.hydrated && layout.isLgUp ? layout.chatWidth : null;
  const railWidthPx = layout.hydrated && layout.isLgUp ? layout.railWidth : null;
  const chatCollapsed = layout.hydrated && layout.isLgUp && layout.chatCollapsed;
  const railCollapsed = layout.hydrated && layout.isLgUp && layout.railCollapsed;

  return (
    <div className="flex h-full w-full flex-col">
      <CanvasHeader videoId={selectedVideoId} />

      <div ref={rowRef} className="flex min-h-0 min-w-0 flex-1 flex-col lg:flex-row">
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
        {chatCollapsed ? (
          <CollapsedPanelStub side="left" label="Chat" onExpand={layout.expandChat} />
        ) : (
          <div
            ref={chatColumnRef}
            style={chatWidthPx != null ? { width: chatWidthPx } : undefined}
            className={`relative flex w-full min-w-0 flex-none flex-col overflow-y-auto border-b border-edge bg-surface transform-gpu lg:border-b-0 lg:border-r ${
              chatWidthPx != null ? "" : "lg:min-w-[380px] lg:max-w-[460px] lg:w-[38%]"
            }`}
            data-director-chat-column="true"
          >
            <ChatCore
              docked={false}
              activeVideoId={selectedVideoId}
              onVideoCreated={(id) => setSelectedVideoId(id)}
              initialMessage={pendingInitialMessage}
            />
          </div>
        )}

        {!chatCollapsed && (
          <PanelDivider
            side="left"
            label="chat"
            measureRef={chatColumnRef}
            min={CHAT_MIN_WIDTH}
            max={CHAT_MAX_WIDTH}
            valueNow={chatMeasuredWidth ?? CHAT_MIN_WIDTH}
            onLiveResize={layout.liveResizeChat}
            onCommitResize={layout.commitResizeChat}
            onCollapse={layout.collapseChat}
          />
        )}

        {/* Canvas column — the altitude-routed stage (Shot / Scene / Timeline).
            `min-w-[320px]` is a real floor, not `min-w-0` — verified the
            CostDial's three totals (SceneAltitudeView.tsx -> CostDial.tsx)
            still render without wrapping/clipping at exactly this width
            with the app sidebar EXPANDED (its widest, 240px — the tightest
            realistic combination). Without a floor here, a flex-1 child
            can be squeezed to 0 by its flex-none siblings; CHAT_MAX_WIDTH/
            RAIL_MAX_WIDTH (usePanelLayout.ts) are sized with this floor in
            mind too, though an aggressive simultaneous drag of both to
            their max on a narrow browser window can still push the row
            wider than the viewport — the canvas itself, and the CostDial
            inside it, never breaks even then; only scoped, deliberately not
            chased further here (see commit message). */}
        <div className="flex min-w-[320px] flex-1 flex-col bg-void">
          <CanvasStage videoId={selectedVideoId} />
        </div>

        {!railCollapsed && (
          <PanelDivider
            side="right"
            label="media rail"
            measureRef={railColumnRef}
            min={RAIL_MIN_WIDTH}
            max={RAIL_MAX_WIDTH}
            valueNow={railMeasuredWidth ?? RAIL_MIN_WIDTH}
            onLiveResize={layout.liveResizeRail}
            onCommitResize={layout.commitResizeRail}
            onCollapse={layout.collapseRail}
          />
        )}

        {/* Right rail — Media / Voice / Music / Cast / Environments. */}
        {railCollapsed ? (
          <CollapsedPanelStub side="right" label="Media rail" onExpand={layout.expandRail} />
        ) : (
          <RightRail videoId={selectedVideoId} widthPx={railWidthPx ?? undefined} panelRef={railColumnRef} />
        )}
      </div>
    </div>
  );
}
