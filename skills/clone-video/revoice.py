#!/usr/bin/env python3
"""clone-video revoice: swap the voice, keep the pixels (speech-to-speech).

Grok genuinely SPEAKS each line, so the mouth is real. We extract grok's audio
and run it through ElevenLabs Voice Changer with the character's pinned voice:
same words, same timing, same rhythm - different throat. Phoneme timing is
preserved, so the lips stay perfectly synced and every clip lands in the same
locked voice. Caveat: the performance is still grok's - a flubbed word is
faithfully flubbed in the new voice.

  revoice.py clip <clip.mp4> <voice_id> <out.mp4>      # revoice one clip
  revoice.py spec <spec.json> <outdir> <voices.json>   # revoice every dialogue clip in place

voices.json: {"RYAN": "<voice_id>", "VANESSA": "<voice_id>"}
Two-speaker clips are split at the speaker boundary (whisper word timing vs the
script turns), each segment converted with its own voice, then rejoined.
Originals are kept as <name>_clip_grokvoice.mp4 - restitch with engine.py
animate afterward (it reuses clips and cached speech-end trims).

Needs ELEVENLABS_API_KEY in ~/economy-fastforward/.env (kie's gateway does NOT
host speech-to-speech - checked 2026-07-04). NO bed of original audio is mixed
underneath by default: the original contains grok's voice saying the same
words, and any amount of it reads as an echo. Ambience survives via
keep_bg=true (STS converts the full mix) when a scene needs its SFX.
"""
import json, os, subprocess, sys, tempfile, urllib.request

ENV = os.path.expanduser("~/economy-fastforward/.env")
STS_MODEL = "eleven_multilingual_sts_v2"
BED_GAIN = 0.0   # original audio under the new voice - DEFAULT 0: the original
                 # contains grok's VOICE saying the same words, so any bed reads
                 # as an echo/double (Ryan heard it immediately, 2026-07-04)
KEEP_BG = True   # LOCKED (Ryan 2026-07-04): convert the FULL MIX so ambience
                 # and SFX ride inside the converted track - variant B won the A/B


def load_key():
    try:
        for line in open(ENV):
            if line.strip().startswith("ELEVENLABS_API_KEY"):
                v = line.split("=", 1)[1].strip()
                if v:
                    return v
    except FileNotFoundError:
        pass
    return os.getenv("ELEVENLABS_API_KEY")


def run_ff(args):
    subprocess.run(["ffmpeg", "-y", *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sts(audio_path, voice_id, key, out_path, keep_bg=KEEP_BG):
    """ElevenLabs speech-to-speech: convert audio to the pinned voice."""
    import mimetypes, uuid
    boundary = uuid.uuid4().hex
    parts = []
    def field(name, value):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    field("model_id", STS_MODEL)
    field("remove_background_noise", "false" if keep_bg else "true")
    data = open(audio_path, "rb").read()
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; "
                 f"filename=\"audio.mp3\"\r\nContent-Type: audio/mpeg\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/speech-to-speech/{voice_id}?output_format=mp3_44100_128",
        data=body, method="POST",
        headers={"xi-api-key": key,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        audio = r.read()
    with open(out_path, "wb") as f:
        f.write(audio)
    return out_path


def revoice_clip(clip, voice_id, out, key=None, bed=BED_GAIN, keep_bg=KEEP_BG):
    key = key or load_key()
    if not key:
        print("ERROR: ELEVENLABS_API_KEY not found"); sys.exit(1)
    with tempfile.TemporaryDirectory() as td:
        raw = os.path.join(td, "raw.mp3")
        conv = os.path.join(td, "conv.mp3")
        run_ff(["-i", clip, "-vn", "-c:a", "libmp3lame", "-q:a", "2", raw])
        sts(raw, voice_id, key, conv, keep_bg=keep_bg)
        if bed > 0:
            # WARNING: the bed contains grok's original voice = audible double
            run_ff(["-i", clip, "-i", conv, "-filter_complex",
                    f"[0:a]volume={bed}[bed];[bed][1:a]amix=inputs=2:duration=first:"
                    "dropout_transition=0:normalize=0[a]",
                    "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                    "-ar", "48000", out])
        else:
            run_ff(["-i", clip, "-i", conv, "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-shortest", out])
    print(f"revoiced -> {out}")


def _speaker_of(sh):
    """Speaker name for a single-voice shot, or None if multi-speaker."""
    d = sh.get("dialogue")
    if not d:
        return None
    if isinstance(d, list):
        names = {t["speaker"] for t in d}
        return names.pop() if len(names) == 1 else None
    # single-string dialogue: infer from spec convention (caller may override
    # with sh["speaker"])
    return sh.get("speaker")


_WHISPER = None

def _whisper_model():
    global _WHISPER
    if _WHISPER is None:
        import whisper
        _WHISPER = whisper.load_model("base")
    return _WHISPER


def _normw(w):
    import unicodedata
    w = unicodedata.normalize("NFD", w.lower())
    return "".join(c for c in w if c.isalnum())


def _split_two_speaker(clip, sh, td):
    """Split a two-speaker clip's audio at the turn boundary.

    Anchors on difflib-MATCHED words (whisper can tokenize 'Supermercado' as
    two words or drop one, so raw word COUNTS point at the wrong spot - live
    finding: Ryan's line tail came out in Vanessa's voice). Falls back to the
    largest inter-word pause near the expected position."""
    import difflib
    turns = sh["dialogue"]
    model = _whisper_model()
    r = model.transcribe(clip, word_timestamps=True)
    words = [w for seg in r["segments"] for w in seg.get("words", [])]
    if not words:
        return [(0.0, 3.0, turns[0]["speaker"]), (3.0, None, turns[1]["speaker"])]
    script_words = (turns[0]["text"] + " " + turns[1]["text"]).split()
    n_first = len(turns[0]["text"].split())
    a = [_normw(w["word"]) for w in words]
    b = [_normw(w) for w in script_words]
    t1_last = t2_first = None
    for blk in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            bi, ai = blk.b + k, blk.a + k
            if bi <= n_first - 1:
                t1_last = ai
            elif t2_first is None:
                t2_first = ai
    boundary = None
    if t1_last is not None and t1_last + 1 < len(words):
        lo = words[t1_last]["end"]
        hi = words[t2_first]["start"] if t2_first is not None and t2_first > t1_last else words[t1_last + 1]["start"]
        boundary = (lo + max(hi, lo)) / 2
    if boundary is None:
        exp = n_first / max(len(script_words), 1) * len(words)
        best, bestgap = None, -1.0
        for i in range(len(words) - 1):
            if abs(i + 1 - exp) <= max(2, 0.3 * len(words)):
                gap = words[i + 1]["start"] - words[i]["end"]
                if gap > bestgap:
                    bestgap, best = gap, i
        boundary = ((words[best]["end"] + words[best + 1]["start"]) / 2
                    if best is not None else words[-1]["end"])
    print(f"[{sh['name']}] turn boundary {boundary:.2f}s "
          f"(anchor={'matched' if t1_last is not None else 'pause'})", flush=True)
    return [(0.0, boundary, turns[0]["speaker"]),
            (boundary, None, turns[1]["speaker"])]


def revoice_spec(spec_path, outdir, voices_path):
    key = load_key()
    if not key:
        print("ERROR: ELEVENLABS_API_KEY not found"); sys.exit(1)
    spec = json.load(open(spec_path))
    voices = json.load(open(voices_path))
    shots = [sh for beat in spec["beats"] for sh in beat if sh.get("dialogue")]
    done = failed = 0
    for sh in shots:
        clip = os.path.join(outdir, sh["name"] + "_clip.mp4")
        backup = os.path.join(outdir, sh["name"] + "_clip_grokvoice.mp4")
        if not os.path.exists(clip):
            print(f"[{sh['name']}] no clip, skipping"); continue
        if os.path.exists(backup):
            print(f"[{sh['name']}] already revoiced"); continue
        try:
            with tempfile.TemporaryDirectory() as td:
                spk = _speaker_of(sh)
                if spk or not isinstance(sh["dialogue"], list):
                    spk = spk or "RYAN"
                    os.rename(clip, backup)
                    revoice_clip(backup, voices[spk], clip, key)
                else:
                    segs = _split_two_speaker(clip, sh, td)
                    raws, convs = [], []
                    for i, (t0, t1, speaker) in enumerate(segs):
                        raw = os.path.join(td, f"seg{i}.mp3")
                        args = ["-i", clip, "-vn", "-ss", str(t0)]
                        if t1:
                            args += ["-to", str(t1)]
                        run_ff(args + ["-c:a", "libmp3lame", "-q:a", "2", raw])
                        conv = os.path.join(td, f"conv{i}.mp3")
                        sts(raw, voices[speaker], key, conv)
                        convs.append(conv)
                    joined = os.path.join(td, "joined.mp3")
                    listp = os.path.join(td, "list.txt")
                    with open(listp, "w") as f:
                        for c in convs:
                            f.write(f"file '{c}'\n")
                    run_ff(["-f", "concat", "-safe", "0", "-i", listp, "-c:a",
                            "libmp3lame", "-q:a", "2", joined])
                    os.rename(clip, backup)
                    run_ff(["-i", backup, "-i", joined, "-map", "0:v:0", "-map", "1:a:0",
                            "-c:v", "copy", "-c:a", "aac", "-ar", "48000",
                            "-shortest", clip])
                    print(f"revoiced (2-speaker) -> {clip}")
            done += 1
        except Exception as e:
            print(f"[{sh['name']}] FAILED: {str(e)[:120]}")
            if os.path.exists(backup) and not os.path.exists(clip):
                os.rename(backup, clip)
            failed += 1
    print(f"=== REVOICE DONE: {done} ok, {failed} failed ===")
    print("Now restitch: engine.py animate <spec.json> <outdir> (clips are reused)")


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "clip":
        bed = float(sys.argv[5]) if len(sys.argv) > 5 else BED_GAIN
        keep_bg = (sys.argv[6].lower() == "true") if len(sys.argv) > 6 else KEEP_BG
        revoice_clip(sys.argv[2], sys.argv[3], sys.argv[4], bed=bed, keep_bg=keep_bg)
    elif cmd == "spec":
        revoice_spec(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
