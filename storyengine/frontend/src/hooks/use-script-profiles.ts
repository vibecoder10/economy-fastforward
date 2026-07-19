"use client";

// One shared query for the script-voice catalog (checklist §2.3, C24) — the
// New Video "Advanced" select (pipeline/page.tsx) and the Script tab's
// ScriptVoiceCard (ScriptVoiceTab.tsx) both call this hook so React Query
// dedupes the request under the SAME ["script-profiles"] key instead of each
// door fetching its own copy (mirrors use-style-presets.ts's rationale).
import { useQuery } from "@tanstack/react-query";
import { getScriptProfiles } from "@/lib/api";

export function useScriptProfiles() {
  return useQuery({
    queryKey: ["script-profiles"],
    queryFn: getScriptProfiles,
    // A near-static, code-derived registry (3 profiles today) — long
    // staleTime avoids a refetch on every tab focus (mirrors
    // use-style-presets.ts's ["style-presets"] query).
    staleTime: 5 * 60_000,
  });
}
