"use client";

// One shared query for the style-presets gallery (checklist §2.1, C21a) — the
// New Video "Look Engine" grid (pipeline/page.tsx) and the chat LOOK card
// (ChatCore.tsx, wired in C21b) both call this hook so React Query dedupes
// the request under the SAME ["style-presets"] key instead of each door
// fetching its own copy (CLAUDE.md StoryEngine protocol: "React Query: new
// ["style-presets"] query, shared... one fetcher").
import { useQuery } from "@tanstack/react-query";
import { getStylePresets } from "@/lib/api";

export function useStylePresets() {
  return useQuery({
    queryKey: ["style-presets"],
    queryFn: getStylePresets,
    // The catalog is a near-static, code-derived table (5 rows today) — long
    // staleTime avoids a refetch on every tab focus for data that changes on
    // a deploy, not per-session (mirrors ScenesWorkspaceTab's ["models"] query).
    staleTime: 5 * 60_000,
  });
}
