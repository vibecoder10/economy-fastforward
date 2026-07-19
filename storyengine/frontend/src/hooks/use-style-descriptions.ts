"use client";

// One shared query for the six-entry "style description" vocabulary
// (checklist §2.1, C21b) — the New Video "Style description" grid
// (pipeline/page.tsx) and the chat LOOK card (ChatCore.tsx) both call this
// hook so React Query dedupes the request under the SAME
// ["style-descriptions"] key, mirroring use-style-presets.ts's precedent
// for the OTHER axis (the 5-row engine gallery).
//
// This replaces frontend/src/lib/visual-presets.ts's hardcoded array. That
// file (and its backend twin, producer_prompt.VISUAL_PRESETS) drifted apart
// by construction — two hand-maintained copies of the same six ids. Now
// there's one live source (backend channel_format.STYLE_DESCRIPTIONS via
// GET /api/style-descriptions) and zero hardcoded frontend copies, except
// the deliberate skew-fallback below.
import { useQuery } from "@tanstack/react-query";
import { getStyleDescriptions, type StyleDescription } from "@/lib/api";

// SKEW-FALLBACK ONLY — not a maintained parallel list. Used ONLY when the
// endpoint request fails (an old backend deployed before this chunk 404s,
// or a genuine network error) so the LOOK pickers never render empty.
// Mirrors ScenesWorkspaceTab.tsx's FALLBACK_WIRED_MODELS pattern: frozen,
// commented, and never read from except as this one safety net. Keep in
// sync by hand ONLY if these six ids/labels/looks ever change on the
// backend (channel_format.STYLE_DESCRIPTIONS) — the live endpoint is always
// the real source of truth.
export const STYLE_DESCRIPTIONS_FALLBACK: StyleDescription[] = [
  { id: "pixar_3d", label: "Pixar 3D", look: "Soft 3D Pixar-style CG, rounded forms, warm cinematic light, subsurface skin, shallow depth of field" },
  { id: "flat_2d", label: "2D flat", look: "Clean 2D flat vector animation, bold flat colors, simple shapes, crisp outlines, minimal shading" },
  { id: "realistic", label: "Realistic", look: "Photorealistic cinematic photography, natural lighting, real textures, shallow depth of field" },
  { id: "anime", label: "Anime", look: "Modern anime cel-shaded illustration, expressive faces, clean linework, soft gradient shading" },
  { id: "watercolor", label: "Watercolor", look: "Warm hand-painted watercolor storybook art, soft edges, textured paper, gentle palette" },
  { id: "comic", label: "Comic", look: "Bold graphic-novel illustration, inked outlines, halftone shading, dynamic high-contrast color" },
];

// Preview image path is a pure filename convention (public/style-icons/
// <id>.png), not server data — unchanged from visual-presets.ts's `icon`
// field, just derived instead of stored.
export const styleDescriptionIcon = (id: string) => `/style-icons/${id}.png`;

export function useStyleDescriptions() {
  const query = useQuery({
    queryKey: ["style-descriptions"],
    queryFn: getStyleDescriptions,
    // Fixed, code-derived vocabulary — long staleTime avoids a refetch on
    // every tab focus (mirrors useStylePresets' reasoning for the sibling axis).
    staleTime: 5 * 60_000,
  });
  const descriptions = query.data?.descriptions?.length
    ? query.data.descriptions
    : query.isError
      ? STYLE_DESCRIPTIONS_FALLBACK
      : [];
  return { ...query, descriptions };
}

export const styleDescriptionById = (
  descriptions: StyleDescription[],
  id?: string | null,
): StyleDescription | undefined => (id ? descriptions.find((d) => d.id === id) : undefined);
