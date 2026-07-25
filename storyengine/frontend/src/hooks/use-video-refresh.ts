"use client";

import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

/**
 * useVideoRefresh — invalidate every per-video TanStack Query key in one
 * call (Phase 0, Task 0.3 of DIRECTOR-CHAT-PLAN.md).
 *
 * There is no query-key factory in this codebase; every call site inlines
 * its own `["key", videoId]` literal. This list was built by grepping every
 * `queryKey: [...]` (and matching `invalidateQueries`) literal that carries
 * `videoId` / `video.id` across `frontend/src`, not copied from the plan.
 *
 * The plan's expected 10 keys (all confirmed present in real call sites):
 *   video, video-script, video-assets, video-actions, production-guide,
 *   segments, video-characters, video-environments, dialogue-map,
 *   video-ledger
 *
 * Four more per-video keys exist that the plan's list did not mention, and
 * are included here so the hook actually lives up to "every per-video key
 * in one call":
 *   - roster-dashboard      (pipeline/[videoId]/page.tsx, RosterStagePanel.tsx, StaticDocuStageRail.tsx)
 *   - video-characters-gate (ScenesWorkspaceTab.tsx)
 *   - drive-script-status   (ScriptVoiceTab.tsx)
 *   - project-cast          (CharactersTab.tsx)
 *
 * `segments` is also keyed as `["segments", videoId, sceneNumber]` in
 * ScriptVoiceTab.tsx. TanStack Query's `invalidateQueries` matches by key
 * *prefix* by default (`exact` is not set), so invalidating `["segments",
 * videoId]` here also invalidates every `["segments", videoId, sceneNumber]`
 * entry — no separate call needed.
 *
 * Not adopted anywhere yet — ships unused. `pipeline/[videoId]/page.tsx` is
 * explicitly out of scope for this task; the Director surface is this
 * hook's first real consumer in a later phase.
 */
const VIDEO_SCOPED_QUERY_KEYS = [
  "video",
  "video-script",
  "video-assets",
  "video-actions",
  "production-guide",
  "segments",
  "video-characters",
  "video-environments",
  "dialogue-map",
  "video-ledger",
  "roster-dashboard",
  "video-characters-gate",
  "drive-script-status",
  "project-cast",
] as const;

export function useVideoRefresh() {
  const queryClient = useQueryClient();

  return useCallback(
    (videoId: string) => {
      return Promise.all(
        VIDEO_SCOPED_QUERY_KEYS.map((key) =>
          queryClient.invalidateQueries({ queryKey: [key, videoId] })
        )
      );
    },
    [queryClient]
  );
}
