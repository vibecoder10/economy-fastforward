---
name: remotion-best-practices
description: Best practices for Remotion - Video creation in React. Use whenever dealing with Remotion code for domain-specific knowledge on animations, captions, audio, sequencing, transitions, and rendering.
metadata:
  tags: remotion, video, react, animation, composition
---

# Remotion Best Practices

Use this skill whenever dealing with Remotion code to obtain domain-specific knowledge.

## Core Topics

### Animations
- Fundamental animation skills for Remotion
- Interpolation curves: linear, easing, spring animations
- Text animation patterns and typography

### Sequencing
- Sequencing patterns: delay, trim, limit duration of items
- Scene transition patterns
- Trimming: cut the beginning or end of animations

### Compositions
- Defining compositions, stills, folders, default props and dynamic metadata
- Dynamically set composition duration, dimensions, and props via calculateMetadata
- Make videos parametrizable by adding a Zod schema

### Assets
- Importing images, videos, audio, and fonts into Remotion
- Always use `<Img>` component over native `<img>` for images
- Embedding videos: trimming, volume, speed, looping, pitch
- Loading Google Fonts and local fonts

### Audio & Sound
- Using audio and sound: importing, trimming, volume, speed, pitch
- Audio visualization: spectrum bars, waveforms, bass-reactive effects
- Sound effects integration
- Getting audio/video duration with Mediabunny

### Captions & Subtitles
- Word-level karaoke captions
- Subtitle rendering and timing synchronization

### Video Operations
- Using FFmpeg for trimming, silence detection
- Transparent video rendering
- Getting video dimensions and duration
- Checking video decode capability with Mediabunny

### Visual Effects
- 3D content using Three.js and React Three Fiber
- Light leak overlay effects using @remotion/light-leaks
- Lottie animation embedding
- GIF display synchronized with timeline
- Chart and data visualization patterns (bar, pie, line, stock)
- Map integration with Mapbox

### Advanced
- Measuring DOM nodes and text dimensions
- Fitting text to containers, checking overflow
- Using TailwindCSS in Remotion
- AI-generated voiceover with ElevenLabs TTS

## Key Rules

1. Always use Remotion's `<Img>`, `<Video>`, `<Audio>` components — not native HTML tags
2. Use `useCurrentFrame()` and `useVideoConfig()` for timing
3. Use `interpolate()` for smooth value transitions
4. Use `<Sequence>` for temporal composition
5. Use `spring()` for natural motion
6. Always specify `fps` in compositions
7. Use `staticFile()` for assets in the public folder
8. Use `delayRender()` / `continueRender()` for async data loading
