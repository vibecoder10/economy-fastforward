# Remotion Rendering System

## How It Works

1. `render_config.json` defines per-scene timing, Ken Burns params, transitions
2. `Main.tsx` maps scenes to Remotion `<Sequence>` components
3. `Scene.tsx` handles: image display, audio sync, karaoke captions, crossfades, Ken Burns motion
4. Captions are word-level karaoke: current word = yellow (#FFE135), past = white, future = gray
5. 6 continuous motion patterns rotate across scenes (push-in, pull-out, pan-left, pan-right, rise, sink)

## Rendering Commands

```bash
cd remotion-video && npm run studio   # Preview
cd remotion-video && npm run render   # Render final MP4 to out/final.mp4
```

## Rules

- Scene.tsx is ~450 lines. Be surgical when editing - test changes in studio first.
- Word-level transcript data lives in `src/captions/Scene [1-20].json`.
- The 4GB swap file is required for rendering on the 8GB VPS. Without it, Remotion OOMs.
- `segmentData.ts` is gitignored - it's generated, not committed.
