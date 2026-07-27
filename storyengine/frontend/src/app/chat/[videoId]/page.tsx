import { DirectorSurface } from "@/components/director/DirectorSurface";

/**
 * The addressable Director surface for one open video (chat-persist fix,
 * 2026-07-27). Root cause this exists for: `selectedVideoId` used to be
 * plain `useState` with nothing in the URL at all (DirectorContext.tsx,
 * before this fix) — so a browser refresh, or sharing/bookmarking the page,
 * always dropped back to the empty Director home. Verified live: opening a
 * video, then reloading `http://localhost:3001/`, landed back on
 * DirectorHome with the chat gone.
 *
 * Route shape: a path segment (`/chat/[videoId]`), not a query string —
 * matching this codebase's existing convention for "a page about one
 * specific video" (`/pipeline/[videoId]`, `/scene-control/[videoId]`; see
 * those page.tsx files). No other entity-scoped route here uses
 * `?videoId=`, so a search param would be the odd one out.
 *
 * This page doesn't need to read the `videoId` param itself — DirectorContext's
 * DirectorProvider (mounted once at the root layout, app/layout.tsx) derives
 * `selectedVideoId` directly from `usePathname()`, which is what lets a
 * plain page reload re-seed it correctly before any component-level effect
 * runs. DirectorSurface then renders the same chat/canvas/rail layout as
 * app/page.tsx and app/chat/page.tsx — just with a video already selected.
 *
 * Scoped by tenant the same way every other `/api/videos/:id` call in this
 * app is: the backend 404s a video id that doesn't belong to the caller's
 * tenant (verified live against the prod API — a foreign-tenant id returns
 * 404, not another tenant's data), so pasting someone else's URL can't leak
 * their video; the child queries (CanvasHeader, SceneAltitudeView, etc.)
 * already render an error state on that 404 rather than a blank/broken page.
 */
export default function ChatVideoPage() {
  return (
    <div className="h-full w-full bg-void">
      <DirectorSurface />
    </div>
  );
}
