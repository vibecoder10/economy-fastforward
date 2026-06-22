// Canonical visual-style presets — the single source of truth for the style
// picker in BOTH the New Video flow (app/pipeline/page.tsx) and the chat-first
// producer (components/chat/ChatHome.tsx). Each carries the LOOK sentence the
// generator front-loads + a preview image at public/style-icons/<id>.png.
// The backend mirrors id -> look in producer_prompt.VISUAL_PRESETS (keep in sync).

export type VisualPreset = { id: string; label: string; look: string; icon: string };

export const VISUAL_PRESETS: VisualPreset[] = [
  { id: "pixar_3d", label: "Pixar 3D", icon: "/style-icons/pixar_3d.png",
    look: "Soft 3D Pixar-style CG, rounded forms, warm cinematic light, subsurface skin, shallow depth of field" },
  { id: "flat_2d", label: "2D flat", icon: "/style-icons/flat_2d.png",
    look: "Clean 2D flat vector animation, bold flat colors, simple shapes, crisp outlines, minimal shading" },
  { id: "realistic", label: "Realistic", icon: "/style-icons/realistic.png",
    look: "Photorealistic cinematic photography, natural lighting, real textures, shallow depth of field" },
  { id: "anime", label: "Anime", icon: "/style-icons/anime.png",
    look: "Modern anime cel-shaded illustration, expressive faces, clean linework, soft gradient shading" },
  { id: "watercolor", label: "Watercolor", icon: "/style-icons/watercolor.png",
    look: "Warm hand-painted watercolor storybook art, soft edges, textured paper, gentle palette" },
  { id: "comic", label: "Comic", icon: "/style-icons/comic.png",
    look: "Bold graphic-novel illustration, inked outlines, halftone shading, dynamic high-contrast color" },
];

export const visualPresetById = (id?: string | null): VisualPreset | undefined =>
  id ? VISUAL_PRESETS.find((p) => p.id === id) : undefined;
