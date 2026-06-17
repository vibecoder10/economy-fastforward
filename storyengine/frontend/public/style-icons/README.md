# Preset visual-style icons

The New Video "Visual style" step shows one preview icon per preset (see
`VISUAL_PRESETS` in `src/app/pipeline/page.tsx`). Drop the six square PNGs here
with these EXACT filenames (same fox subject, different style — generated from the
prompts in `tasks/new-video-visual-style-step-spec.md` Appendix A):

| Preset | File |
|--------|------|
| Pixar 3D    | `pixar_3d.png` |
| 2D flat     | `flat_2d.png` |
| Realistic   | `realistic.png` |
| Anime       | `anime.png` |
| Watercolor  | `watercolor.png` |
| Comic       | `comic.png` |

Square PNGs (1:1); the form downscales them to ~64px. Until they're added, the
preset buttons render a broken-image placeholder (harmless — the styles still work).
