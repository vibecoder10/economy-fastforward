"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clapperboard, Film, Users, X } from "lucide-react";
import { useDirector, type SelectedEntity } from "./DirectorContext";
import { DirectorHome } from "./DirectorHome";
import { CanvasHeader } from "./CanvasHeader";
import { CanvasStage } from "./CanvasStage";
import { RightRail } from "./RightRail";
import { ChatCore } from "@/components/chat/ChatCore";
import { CollapsedPanelStub, PanelDivider } from "./PanelResizeControls";
import { CHAT_MAX_WIDTH, CHAT_MIN_WIDTH, RAIL_MAX_WIDTH, RAIL_MIN_WIDTH, usePanelLayout } from "./usePanelLayout";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { getVideoAssets, getVideoCharacters, getEnvironments, type ChatUiContext } from "@/lib/api";

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
  const {
    selectedVideoId,
    setSelectedVideoId,
    altitude,
    focusedShotId,
    selectedEntity,
    railTab,
    pendingInitialMessage,
    setPendingInitialMessage,
    pendingInitialIntent,
    setPendingInitialIntent,
    pendingInitialTurn,
    setPendingInitialTurn,
  } = useDirector();
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
    if (pendingInitialIntent) setPendingInitialIntent(null);
    // Safety net, not the main fix (ChatCore's own consume-once effect is —
    // see PendingInitialTurn's doc comment): a `pendingInitialTurn` that
    // belongs to a DIFFERENT video than the one now open must never leak
    // forward — e.g. the creator bounced to a different video (Recent
    // Videos) before the first one's seed turn ever got picked up. Scoped
    // to "different video", not "any change", so THIS video's own
    // in-flight/just-finished seed turn (written by ChatCore in the SAME
    // commit this effect runs in, so it's read here as whatever it was
    // BEFORE that write — i.e. still null the very first time this effect
    // fires for a brand-new video) is never wiped by the very transition
    // that created it.
    if (pendingInitialTurn && pendingInitialTurn.videoId !== selectedVideoId) {
      setPendingInitialTurn(null);
    }
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
    return (
      <ErrorBoundary label="home screen">
        <DirectorHome />
      </ErrorBoundary>
    );
  }

  // What the canvas/rail are showing right now (DIRECTOR-CHAT-PLAN.md Task
  // 5.4a) — sent on every turn so "make him older" resolves to the actual
  // shot/character on screen instead of the classifier guessing. `scene`/
  // `index` are deliberately omitted: there is no "current scene" concept on
  // this surface (SceneAltitudeView lists every scene at once, unlike the
  // old per-image pipeline dock those two fields were built for) —
  // `focusedAssetId` is this surface's equivalent, more precise signal, and
  // the backend already resolves an asset id ahead of any scene/index guess
  // (routes/chat.py `_resolve_prompt_target`).
  const uiContext: ChatUiContext = {
    altitude,
    focusedAssetId: focusedShotId,
    railTab,
    selectedEntityId: selectedEntity?.id ?? null,
    selectedEntityType: selectedEntity?.kind ?? null,
  };

  // Only apply a custom width once hydrated AND at `lg`+ — before hydration
  // or below `lg`, render exactly the original classes (no inline style),
  // so a fresh visitor and a narrow viewport both see today's layout.
  const chatWidthPx = layout.hydrated && layout.isLgUp ? layout.chatWidth : null;
  const railWidthPx = layout.hydrated && layout.isLgUp ? layout.railWidth : null;
  const chatCollapsed = layout.hydrated && layout.isLgUp && layout.chatCollapsed;
  const railCollapsed = layout.hydrated && layout.isLgUp && layout.railCollapsed;

  return (
    <div className="flex h-full w-full flex-col">
      {/* Error boundaries wrap each panel individually, NOT the whole
          surface in one — bug 2 fix (2026-07-27 audit): before this,
          nothing in layout.tsx / DirectorSurface.tsx / CanvasStage.tsx
          caught a render exception, so one uncaught throw in ANY of
          header/chat/canvas/rail took the entire Director surface down.
          `resetKeys={[selectedVideoId]}` on each so a crash tied to one
          video doesn't stay stuck showing its fallback after switching to a
          different, working video. CanvasStage.tsx and SceneAltitudeView.tsx
          are NOT touched here on purpose — another workstream has live
          edits in progress there; wrapping from this file gives the same
          protection without adding a diff to either. */}
      <ErrorBoundary label="header" resetKeys={[selectedVideoId]}>
        <CanvasHeader videoId={selectedVideoId} />
      </ErrorBoundary>

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
            anything else. `uiContext` now carries altitude/focusedAssetId/
            railTab/selectedEntity state (DIRECTOR-CHAT-PLAN.md Task 5.4a,
            built just above) — no longer left unset. `selectionChip` is a
            separate prop (not folded into uiContext, which is opaque data
            for the backend) so the creator can SEE what that context object
            is about to target; see `SelectionChip` below. */}
        {/* `relative` + `transform-gpu` make this column a CSS containing
            block. ChatCore's own only truly `fixed` element is the
            `fixed inset-0 z-10` click-outside backdrop behind the
            chat-history dropdown (ChatHistoryMenu) — it resolves against
            THIS column instead of the viewport, so clicking the
            canvas/rail while that dropdown is open no longer auto-closes
            it (clicking anywhere inside the column, or picking an item,
            still does). `transform` (any non-none value, `translateZ(0)`
            here) is what the CSS spec keys the fixed-positioning
            containing block off of.
            Layout fix (2026-07-27, live bug — composer floated mid-column
            on top of messages/progress cards): this column must NOT be the
            scrolling element. ChatCore's undocked layout now owns its own
            internal `flex-1 min-h-0 overflow-y-auto` scroll region, with
            its composer pinned via `absolute bottom-0` against a
            non-scrolling `h-full` wrapper — that wrapper only gets a
            correct, definite height to stretch into if THIS column stops
            scrolling itself and lets its child stretch to fill it instead
            (flex row cross-axis stretch, already happening here). Hence
            `overflow-hidden`, not `overflow-y-auto` — any scrolling now
            happens strictly inside ChatCore, never at this outer level. */}
        {chatCollapsed ? (
          <CollapsedPanelStub side="left" label="Chat" onExpand={layout.expandChat} />
        ) : (
          <div
            ref={chatColumnRef}
            style={chatWidthPx != null ? { width: chatWidthPx } : undefined}
            className={`relative flex w-full min-w-0 flex-none flex-col overflow-hidden border-b border-edge bg-surface transform-gpu lg:border-b-0 lg:border-r ${
              chatWidthPx != null ? "" : "lg:min-w-[380px] lg:max-w-[460px] lg:w-[38%]"
            }`}
            data-director-chat-column="true"
          >
            <ErrorBoundary label="chat" resetKeys={[selectedVideoId]}>
              <ChatCore
                docked={false}
                activeVideoId={selectedVideoId}
                onVideoCreated={(id) => setSelectedVideoId(id)}
                initialMessage={pendingInitialMessage}
                initialIntent={pendingInitialIntent}
                pendingInitialTurn={pendingInitialTurn}
                setPendingInitialTurn={setPendingInitialTurn}
                uiContext={uiContext}
                selectionChip={<SelectionChip videoId={selectedVideoId} />}
              />
            </ErrorBoundary>
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
          <ErrorBoundary label="canvas" resetKeys={[selectedVideoId]}>
            <CanvasStage videoId={selectedVideoId} />
          </ErrorBoundary>
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
          <ErrorBoundary label="media rail" resetKeys={[selectedVideoId]}>
            <RightRail videoId={selectedVideoId} widthPx={railWidthPx ?? undefined} panelRef={railColumnRef} />
          </ErrorBoundary>
        )}
      </div>
    </div>
  );
}

/**
 * "Show the current target somewhere honest and small" — the visible half
 * of Task 5.4a. Renders directly above ChatCore's composer (passed in as
 * the `selectionChip` prop) naming whatever `uiContext.focusedAssetId` /
 * `selectedEntityId` is about to send, with a one-tap clear. Reads the
 * SAME cached queries SceneAltitudeView/RightRail already fired
 * (`["video-assets", videoId]`, `["video-characters-gate", videoId]`,
 * `["video-environments", videoId]` — React Query dedupes by key, so this
 * is a cache hit in the normal case, not a second network round-trip) just
 * to resolve a human label (a shot's scene.index, a character/environment's
 * name) for an id DirectorContext only stores as a bare string.
 *
 * A separate component (not inlined in DirectorSurface) on purpose: these
 * `useQuery` calls must never run before DirectorSurface's own early
 * `if (selectedVideoId === null) return <DirectorHome />` — mounting them
 * here, where `videoId` is only ever a real string, keeps that guard a
 * plain hooks-safe early return instead of a conditional hook call.
 */
function SelectionChip({ videoId }: { videoId: string }) {
  const { focusedShotId, setFocusedShotId, selectedEntity, setSelectedEntity } = useDirector();
  const hasSelection = !!focusedShotId || !!selectedEntity;

  const assetsQuery = useQuery({
    queryKey: ["video-assets", videoId],
    queryFn: () => getVideoAssets(videoId),
    enabled: !!focusedShotId,
  });
  const charactersQuery = useQuery({
    queryKey: ["video-characters-gate", videoId],
    queryFn: () => getVideoCharacters(videoId),
    enabled: selectedEntity?.kind === "character",
  });
  const environmentsQuery = useQuery({
    queryKey: ["video-environments", videoId],
    queryFn: () => getEnvironments(videoId),
    enabled: selectedEntity?.kind === "environment",
  });

  if (!hasSelection) return null;

  let icon = <Film size={12} />;
  let label = "Selected shot";
  let onClear = () => setFocusedShotId(null);

  if (focusedShotId) {
    const asset = assetsQuery.data?.find((a) => a.id === focusedShotId);
    label = asset ? `Shot ${asset.scene ?? "?"}.${asset.image_index ?? "?"}` : "Selected shot";
    onClear = () => setFocusedShotId(null);
  } else if (selectedEntity?.kind === "character") {
    const character = charactersQuery.data?.characters.find((c) => c.id === selectedEntity.id);
    icon = <Users size={12} />;
    label = character ? character.name : "Selected character";
    onClear = () => setSelectedEntity(null);
  } else if (selectedEntity?.kind === "environment") {
    const environment = environmentsQuery.data?.environments.find((e) => e.id === selectedEntity.id);
    icon = <Clapperboard size={12} />;
    label = environment ? environment.name : "Selected location";
    onClear = () => setSelectedEntity(null);
  }

  return (
    <div className="mb-1.5 flex items-center justify-between gap-2 rounded-full px-3 py-1.5" style={{ background: "var(--turquoise-dim)", border: "1px solid var(--turquoise-dim)" }}>
      <span className="inline-flex min-w-0 items-center gap-1.5 text-xs font-medium" style={{ color: "var(--turquoise)" }}>
        {icon}
        <span className="truncate">Talking about: {label}</span>
      </span>
      <button
        type="button"
        onClick={onClear}
        aria-label={`Clear ${label} as chat's target`}
        title="Clear — the next message won't be pinned to this"
        className="shrink-0 rounded-full p-0.5 transition-colors hover:brightness-125"
        style={{ color: "var(--turquoise)" }}
      >
        <X size={13} />
      </button>
    </div>
  );
}
