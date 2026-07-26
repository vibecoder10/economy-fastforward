# Scene Control synthetic proof assets

These assets are local, fictional, and provider-free. The five MP4 files are
deterministic FFmpeg vector scenes. The four WAV files were synthesized locally
with macOS `say` at 205 words per minute, using Samantha for Mara and Alex for
Elias, then normalized with FFmpeg to 48 kHz stereo PCM and the exact
frame-bound duration:

- `mara-signal.wav`: “The signal is inside.” — 40 frames
- `elias-knows.wav`: “Then it knows we're here.” — 44 frames
- `mara-kill.wav`: “Kill the transmitter.” — 40 frames
- `elias-did.wav`: “Already did.” — 44 frames

`manifest.json` binds every tracked byte. The staging script verifies those
hashes before copying the same assets into `public/director-scene-proof/`.
