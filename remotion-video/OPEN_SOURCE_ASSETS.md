# Open-source runtime assets

The motion library imports `@fontsource/noto-sans` at exact version `5.2.5`.
The package is SIL Open Font License 1.1 and is bundled locally by Remotion; no
runtime network request is made. Package bytes are pinned by the npm lockfile
integrity field. Source: https://github.com/fontsource/font-files

The WAV fixtures under `public/motion-audio/` are generated from mathematical
waveforms by `scripts/generate-motion-audio.mjs` and contain no third-party
recording. The repository-level ignore rules intentionally exclude generated
media, so `prestudio`, `prebuild`, `test:motion-library`, and
`render:motion-preview` regenerate them on a clean checkout. Exact expected
SHA-256 values live in `src/motion-library/contracts.ts` and are enforced by
the motion-library test suite.
