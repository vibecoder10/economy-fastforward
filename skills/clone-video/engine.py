#!/usr/bin/env python3
"""clone-video engine: two-stage build of the content-engine pipeline so storyboards
get approved BEFORE animation money is spent.

  engine.py estimate <spec.json>              # cost quote, no spend
  engine.py sheet <prompt.txt> <outdir>       # ONE storyboard-sheet image (all panels + captions) - review BEFORE keyframes
  engine.py storyboard <spec.json> <outdir>   # cast sheet + every keyframe, then STOP
  engine.py thumbnail <prompt.txt> <outdir>   # modeled thumbnail from a blueprint prompt
  engine.py animate <spec.json> <outdir>      # clips + trim + stitch (needs storyboard done)
  engine.py upload <local_image>              # host a local seed so kie.ai can fetch it

Same spec.json shape as content-engine (settings / seed_urls / reference / beats),
plus format routing:
  settings.format = "kenburns"      -> every shot is a still moved by ffmpeg (free)
  shot.kenburns = "zoom_in|zoom_out|pan_left|pan_right"  -> per-shot override either way
  settings.narration_audio = <path> -> voiceover mixed over the cut (clips ducked to 25%)
Keyframe URLs persist in <outdir>/urls.json so animate can run in a later session.
To regenerate one shot: delete its _kf.png and its urls.json entry, rerun storyboard.
Regenerating a beat's master (first shot) means also deleting that beat's angle kfs.
Reads KIE_AI_API_KEY from ~/economy-fastforward/.env. Grok ~$0.14/shot.
"""
import json, math, os, subprocess, sys, threading, time, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

ENV_PATHS = [os.path.expanduser("~/economy-fastforward/.env"),
             os.path.expanduser("~/economy-fastforward/storyengine/backend/.env")]
CREATE = "https://api.kie.ai/api/v1/jobs/createTask"
RECORD = "https://api.kie.ai/api/v1/jobs/recordInfo"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
CREDIT = 0.005  # USD per kie.ai credit
MAX_PARALLEL = int(os.getenv("CLONE_PARALLEL", "8"))  # concurrent kie tasks (platform parity)

# --- Smart shot timing + motion guards (StoryEngine parity, see PARITY.md) ---
# Grok speaks ~2.7 words/sec (measured on the platform). A speaking clip must
# hold the whole line, but an over-long clip makes grok ad-lib garbage past the
# line - so the clip ends when the speech does.
WORDS_PER_SEC_SPOKEN = 2.7
SPEECH_BUFFER = 0.3      # headroom so the last word plus a beat fits
DIALOGUE_LEAD = 0.5      # characters rarely mouth words in the very first frames
SPEECH_TAIL = 1.0        # air AFTER the last word so the scene finishes (Ryan: lines were cut off)
GROK_FLOOR, GROK_CAP = 6, 15
GROK_TIER_CREDITS = {6: 20, 10: 30, 15: 40}   # $0.10 / $0.15 / $0.20; between = next tier up
SILENT_CLIP_GAIN = 0.06  # grok ad-libs stray lines over b-roll; duck to faint room tone

NO_NEW_PEOPLE = (
    "STRICT: do not add any person or character who is not already visible "
    "in the image. If someone is only implied at the frame edge (shoes, "
    "feet, a hand, a shadow), they stay exactly that - never walk them into "
    "frame, never reveal their face or body. ")
CUTAWAY = (
    "STRICT: this is a cutaway shot with NO PEOPLE. Never show a person, "
    "face or body - animate only the scene, objects or animal exactly as "
    "shown. At most a hand or foot may enter the frame edge. ")
OFF_SCREEN_SPEAKER = (
    "STRICT: if the speaker is not visible in the image, their voice comes "
    "from OFF-SCREEN - never add them or any new person to the scene. Keep "
    "the framing and everything visible exactly as shown.")
DEFAULT_MOTION = (
    "Slow push-in on the main subject. Keep the characters, art style, and "
    "composition exactly as shown, and animate only what is already in the frame.")


def dialogue_words(dlg):
    """dialogue is a string (one speaker) or a list of {speaker, text} turns
    (SE-parity multi-speaker chaining)."""
    if not dlg:
        return 0
    if isinstance(dlg, list):
        return sum(len((d.get("text") or "").split()) for d in dlg)
    return len(dlg.split())


def speech_secs(text):
    words = dialogue_words(text) if not isinstance(text, str) else len((text or "").split())
    return words / WORDS_PER_SEC_SPOKEN + SPEECH_BUFFER if words else 0.0


def shot_timing(sh, settings):
    """(gen_duration, cut, is_dialogue) for one shot - the auto smart selector.
    Dialogue: clip sized to the line (2.7 w/s + buffer + lead), cut = whole take.
    Silent grok: clip covers the edit cut plus the trimmed lead-in.
    Ken Burns: ffmpeg renders the exact cut; no generation duration."""
    cut = float(sh["cut"])
    if kb_of(sh, settings):
        return None, cut, False
    if sh.get("dialogue"):
        need = dialogue_words(sh["dialogue"]) / WORDS_PER_SEC_SPOKEN + SPEECH_BUFFER + DIALOGUE_LEAD
        gen = max(GROK_FLOOR, min(GROK_CAP, math.ceil(need + SPEECH_TAIL)))
        # provisional cut - animate refines it from the MEASURED end of speech
        return gen, float(min(max(cut, round(need + SPEECH_TAIL, 1)), gen)), True
    start = float(settings.get("start_offset", 0.8))
    gen = max(GROK_FLOOR, min(GROK_CAP, math.ceil(cut + start)))
    return gen, cut, False


def grok_credits(gen_dur):
    for t in sorted(GROK_TIER_CREDITS):
        if gen_dur <= t:
            return GROK_TIER_CREDITS[t]
    return GROK_TIER_CREDITS[max(GROK_TIER_CREDITS)]


def build_motion(sh):
    """Motion prompt with the platform's people rules baked in."""
    motion = (sh.get("motion") or "").strip() or DEFAULT_MOTION
    dlg = sh.get("dialogue")
    if dlg:
        if isinstance(dlg, list):
            # SE-parity multi-speaker chaining (native_speaking_prompt): each
            # turn spoken in order by its own character, joined with "Then".
            spoken = ". Then ".join(
                f'{d["speaker"]} speaks with clear natural mouth movement, '
                f'lip-synced, saying exactly these words: "{d["text"]}"'
                for d in dlg)
        else:
            spoken = ("The character speaks with clear natural mouth movement, "
                      f'lip-synced, saying exactly these words: "{dlg}"')
        return (f"{motion} {spoken}. The words must be spoken exactly as written "
                "- no other dialogue, no narration. The speaking starts right "
                "away. Expressive faces, natural small gestures; whoever is not "
                "speaking reacts subtly but does not talk. " + OFF_SCREEN_SPEAKER)
    return (CUTAWAY if sh.get("cutaway") else NO_NEW_PEOPLE) + motion


def load_key():
    for p in ENV_PATHS:
        try:
            with open(p) as f:
                for line in f:
                    if line.strip().startswith("KIE_AI_API_KEY"):
                        v = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if v:
                            return v
        except FileNotFoundError:
            continue
    return os.getenv("KIE_AI_API_KEY")


def post_json(url, payload, key):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"_error": e.read().decode()[:800]}


def poll(task_id, key, max_attempts=240, interval=5):
    url = RECORD + "?" + urllib.parse.urlencode({"taskId": task_id})
    for i in range(max_attempts):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = (json.loads(r.read().decode()).get("data") or {})
        except Exception as e:
            print(f"    poll error: {e}"); time.sleep(interval); continue
        st, state = data.get("status"), data.get("state")
        if st == 3 or str(st).lower() in ("failed", "failure", "error") or \
           str(state).lower() in ("fail", "failed", "failure", "error"):
            print(f"    FAILED: {data.get('failMsg') or data.get('errorMessage') or data}")
            return None, data
        rj = data.get("resultJson")
        if rj:
            rd = json.loads(rj) if isinstance(rj, str) else rj
            if rd.get("resultUrls"):
                return rd["resultUrls"], data
        if i % 6 == 0:
            print(f"    ...polling ({i}) state={state} status={st}", flush=True)
        time.sleep(interval)
    return None, {}


def gen(model, inp, key, label):
    print(f"[{label}] {model} ...", flush=True)
    status, resp = post_json(CREATE, {"model": model, "input": inp}, key)
    if status != 200:
        print(f"[{label}] HTTP {status}: {resp}"); return None
    tid = (resp.get("data") or {}).get("taskId")
    if not tid:
        print(f"[{label}] no taskId: {resp}"); return None
    urls, data = poll(tid, key)
    if not urls:
        print(f"[{label}] FAILED"); return None
    print(f"[{label}] ok ({data.get('creditsConsumed')} cr)", flush=True)
    return urls[0]


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


def upload(path):
    out = subprocess.run(["curl", "-fsS", "-A", UA, "-F", "reqtype=fileupload",
        "-F", f"fileToUpload=@{path}", "https://catbox.moe/user/api.php"],
        capture_output=True, text=True, timeout=120)
    if out.stdout.strip().startswith("http"):
        print(out.stdout.strip()); return out.stdout.strip()
    print(f"ERROR upload: {out.stderr}", file=sys.stderr); sys.exit(1)


def target_wh(res, aspect):
    base = {"480p": 480, "720p": 720, "1080p": 1080}.get(res, 720)
    long = (base * 16 // 9) // 2 * 2
    return (base, long) if aspect == "9:16" else (long, base)


def run_ff(args):
    subprocess.run(["ffmpeg", "-y", *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def shots_of(spec):
    return [s for beat in spec["beats"] for s in beat]


def urls_path(outdir):
    return os.path.join(outdir, "urls.json")


def load_urls(outdir):
    try:
        return json.load(open(urls_path(outdir)))
    except FileNotFoundError:
        return {"cast": None, "kf": {}}


def save_urls(outdir, state):
    with open(urls_path(outdir), "w") as f:
        json.dump(state, f, indent=2)


def kb_of(sh, settings):
    """Ken Burns direction for a shot, or None if it animates with grok/seedance.
    Per-shot "kenburns" overrides; settings.format=="kenburns" defaults every shot."""
    if sh.get("kenburns"):
        return sh["kenburns"]
    if settings.get("format") == "kenburns":
        return "zoom_in"
    return None


def estimate(spec):
    s = spec.get("settings", {})
    seed = s.get("animator") == "seedance"
    credits = 10 + 10  # cast sheet + modeled thumbnail
    table, runtime = [], 0.0
    for sh in shots_of(spec):
        gen, cut, is_dlg = shot_timing(sh, s)
        runtime += cut
        if gen is None:
            kind, cr = "kenburns:" + (kb_of(sh, s) or ""), 10
        elif seed:
            kind, cr = "seedance", 10 + 60
        else:
            kind, cr = ("dialogue" if is_dlg else "grok"), 10 + grok_credits(gen)
        credits += cr
        table.append({"shot": sh["name"], "type": kind, "gen_sec": gen,
                      "cut_sec": round(cut, 1), "credits": cr})
    print(json.dumps({"shots": len(table), "runtime_sec": round(runtime, 1),
                      "credits": credits, "est_total_usd": round(credits * CREDIT, 2),
                      "timing": table,
                      "note": "auto-sized: dialogue = words/2.7+buffer (clip ends when the "
                              "line does), silent grok = cut+lead, kenburns = free ffmpeg. "
                              "Grok billed at named tiers 6/10/15s. Includes cast sheet + "
                              "thumbnail (10cr each). Confirm rates in your kie.ai dashboard."},
                     indent=2))


def storyboard(spec, outdir):
    key = load_key()
    if not key:
        print("ERROR: KIE_AI_API_KEY not found"); sys.exit(1)
    os.makedirs(outdir, exist_ok=True)
    s = spec.get("settings", {})
    aspect = s.get("aspect_ratio", "16:9")
    rres = s.get("ref_resolution", "2K")
    seeds = spec.get("seed_urls") or []
    state = load_urls(outdir)

    # 1. cast sheet
    cast_png = os.path.join(outdir, "0_cast_sheet.png")
    if state.get("cast") and os.path.exists(cast_png):
        print("[skip] cast sheet done")
    else:
        rp = spec["reference"]["prompt"]
        if seeds:
            cast = gen("gpt-image-2-image-to-image",
                       {"prompt": rp, "input_urls": seeds, "aspect_ratio": aspect, "resolution": rres},
                       key, "cast sheet (seed)")
        else:
            cast = gen("gpt-image-2-text-to-image",
                       {"prompt": rp, "aspect_ratio": aspect, "resolution": rres}, key, "cast sheet")
        if not cast:
            print("cast sheet failed"); sys.exit(1)
        download(cast, cast_png)
        state["cast"] = cast
        save_urls(outdir, state)
    cast = state["cast"]

    # 2. keyframes in two PARALLEL waves (platform parity - concurrent tasks):
    # wave 1 = every beat's master (anchored on cast), wave 2 = angle shots
    # (anchored on cast + their master). Independent shots never wait in line.
    lock = threading.Lock()

    def kf_done(name):
        return state["kf"].get(name) and os.path.exists(os.path.join(outdir, name + "_kf.png"))

    def make_kf(sh, input_urls, label):
        k = gen("gpt-image-2-image-to-image",
                {"prompt": sh["image"], "input_urls": input_urls,
                 "aspect_ratio": aspect, "resolution": rres}, key, label)
        if k:
            download(k, os.path.join(outdir, sh["name"] + "_kf.png"))
            with lock:
                state["kf"][sh["name"]] = k
                save_urls(outdir, state)
        return sh["name"], k

    def run_wave(jobs):
        failed = []
        if not jobs:
            return failed
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
            futs = [ex.submit(make_kf, sh, urls, lbl) for sh, urls, lbl in jobs]
            for f in as_completed(futs):
                name, k = f.result()
                if not k:
                    failed.append(name)
        return failed

    wave1 = []
    for beat in spec["beats"]:
        m = beat[0]
        if kf_done(m["name"]):
            print(f"[skip] {m['name']} kf done")
        else:
            wave1.append((m, [cast], m["name"] + " kf*"))
    failed = run_wave(wave1)
    if failed:
        print(f"MASTER KEYFRAMES FAILED: {failed} - rerun storyboard to retry"); sys.exit(1)

    wave2 = []
    for beat in spec["beats"]:
        mk = state["kf"][beat[0]["name"]]
        for sh in beat[1:]:
            if kf_done(sh["name"]):
                print(f"[skip] {sh['name']} kf done"); continue
            sh2 = dict(sh)
            sh2["image"] = (sh["image"] + " Match the lighting, wardrobe and setting "
                            "of the attached reference; only the camera angle changes.")
            wave2.append((sh2, [cast, mk], sh["name"] + " kf"))
    failed = run_wave(wave2)
    if failed:
        print(f"KEYFRAMES FAILED: {failed} - rerun storyboard to retry"); sys.exit(1)

    print("=== STORYBOARD DONE ===", flush=True)
    print(f"cast sheet: {cast_png}")
    for sh in shots_of(spec):
        print(f"keyframe: {os.path.join(outdir, sh['name'] + '_kf.png')}")
    print("Review these, then run: engine.py animate <spec.json> <outdir>")


def sheet(prompt_path, outdir):
    """ONE storyboard-sheet image: every shot as a numbered panel with a caption
    strip (shot number, time, shot type, script line). Generated BEFORE any
    per-shot keyframes - review the whole film in one cheap call (~$0.05),
    then spend on full-res generation only after it passes. Anchors on the
    cast sheet when urls.json already has one."""
    key = load_key()
    if not key:
        print("ERROR: KIE_AI_API_KEY not found"); sys.exit(1)
    os.makedirs(outdir, exist_ok=True)
    prompt = open(prompt_path).read().strip()
    state = load_urls(outdir)
    if state.get("cast"):
        url = gen("gpt-image-2-image-to-image",
                  {"prompt": prompt, "input_urls": [state["cast"]],
                   "aspect_ratio": "16:9", "resolution": "2K"}, key, "storyboard sheet")
    else:
        url = gen("gpt-image-2-text-to-image",
                  {"prompt": prompt, "aspect_ratio": "16:9", "resolution": "2K"},
                  key, "storyboard sheet")
    if not url:
        sys.exit(1)
    out = os.path.join(outdir, "storyboard_sheet.png")
    download(url, out)
    print(f"sheet: {out}")


def thumbnail(prompt_path, outdir):
    key = load_key()
    if not key:
        print("ERROR: KIE_AI_API_KEY not found"); sys.exit(1)
    os.makedirs(outdir, exist_ok=True)
    prompt = open(prompt_path).read().strip()
    url = gen("gpt-image-2-text-to-image",
              {"prompt": prompt, "aspect_ratio": "16:9", "resolution": "2K"}, key, "thumbnail")
    if not url:
        # platform image policy: GPT Image 2 first, nano-banana-2 fallback
        # (GPT refuses some innocent prompts; nano is the relief valve)
        url = gen("nano-banana-2",
                  {"prompt": prompt, "aspect_ratio": "16:9"}, key, "thumbnail (nano fallback)")
    if not url:
        sys.exit(1)
    out = os.path.join(outdir, "thumbnail_new.png")
    download(url, out)
    print(f"thumbnail: {out}")


def kenburns_render(kf_png, direction, cut, w, h, out):
    """Free slow move on a still: zoom_in, zoom_out, pan_left, pan_right.
    Upscale first so zoompan does not jitter; silent audio track so concat works."""
    frames = max(int(cut * 24), 24)
    center = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    z = {
        "zoom_in":  f"z='min(zoom+0.0012,1.30)':{center}",
        "zoom_out": f"z='if(lte(zoom,1.0),1.30,max(zoom-0.0012,1.0))':{center}",
        "pan_right": f"z='1.15':x='(iw-iw/zoom)*on/{frames - 1}':y='ih/2-(ih/zoom/2)'",
        "pan_left":  f"z='1.15':x='(iw-iw/zoom)*(1-on/{frames - 1})':y='ih/2-(ih/zoom/2)'",
    }.get(direction) or f"z='min(zoom+0.0012,1.30)':{center}"
    vf = (f"scale=8000:-1,zoompan={z}:d={frames}:s={w}x{h}:fps=24,format=yuv420p")
    run_ff(["-loop", "1", "-i", kf_png, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-vf", vf, "-t", str(cut), "-r", "24",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-ar", "48000", "-shortest", out])
    return out


def clip_seconds(path):
    out = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def measure_speech_ends(items, outdir, state):
    """Whisper-measure where speech actually ENDS in each dialogue clip so the
    trim can leave SPEECH_TAIL of air instead of guessing from word count.
    Cached in urls.json under speech_end. Falls back silently if whisper is
    unavailable."""
    todo = [(name, path) for name, path in items
            if name not in state.setdefault("speech_end", {})]
    if not todo:
        return
    try:
        import whisper
    except ImportError:
        print("whisper unavailable - using estimated cuts")
        return
    model = whisper.load_model("base")
    for name, path in todo:
        try:
            r = model.transcribe(path, word_timestamps=True)
            ends = [w["end"] for seg in r["segments"] for w in seg.get("words", [])]
            state["speech_end"][name] = round(max(ends), 2) if ends else None
            print(f"[{name}] speech ends {state['speech_end'][name]}s", flush=True)
        except Exception as e:
            print(f"[{name}] speech measure failed: {str(e)[:80]}")
            state["speech_end"][name] = None
    save_urls(outdir, state)


def animate(spec, outdir):
    key = load_key()
    if not key:
        print("ERROR: KIE_AI_API_KEY not found"); sys.exit(1)
    s = spec.get("settings", {})
    aspect = s.get("aspect_ratio", "16:9")
    vres = s.get("video_resolution", "720p")
    start = str(s.get("start_offset", "0.8"))
    animator = s.get("animator", "grok")
    state = load_urls(outdir)
    cast = state.get("cast")

    missing = [sh["name"] for sh in shots_of(spec) if not state["kf"].get(sh["name"])]
    if missing or not cast:
        print(f"ERROR: storyboard incomplete (missing: {missing or 'cast sheet'}). Run storyboard first.")
        sys.exit(1)

    w, h = target_wh(vres, aspect)
    narr = s.get("narration_audio")
    ordered = []  # (name, clip_path, cut, is_kenburns, is_dialogue)
    pending = []  # model clips to generate in parallel
    for sh in shots_of(spec):
        clip = os.path.join(outdir, sh["name"] + "_clip.mp4")
        kb = kb_of(sh, s)
        gen_dur, cut, is_dlg = shot_timing(sh, s)
        if os.path.exists(clip):
            print(f"[skip] {sh['name']} clip done")
            ordered.append((sh["name"], clip, cut, bool(kb), is_dlg)); continue
        if kb:
            print(f"[{sh['name']}] kenburns {kb} (free)", flush=True)
            kenburns_render(os.path.join(outdir, sh["name"] + "_kf.png"), kb,
                            cut, w, h, clip)
            ordered.append((sh["name"], clip, cut, True, False)); continue
        ordered.append((sh["name"], clip, cut, False, is_dlg))
        pending.append((sh, gen_dur, clip))

    # all model clips run in PARALLEL - each depends only on its own keyframe
    # (platform parity: the executor animates cards concurrently)
    def make_clip(sh, gen_dur, clip):
        motion = build_motion(sh)
        kf = state["kf"][sh["name"]]
        if animator == "seedance":
            c = gen("bytedance/seedance-2-fast",
                    {"prompt": motion, "first_frame_url": kf, "reference_image_urls": [cast],
                     "aspect_ratio": aspect, "resolution": vres,
                     "duration": min(10, gen_dur), "generate_audio": True},
                    key, sh["name"] + " seedance")
        else:
            c = gen("grok-imagine/image-to-video",
                    {"image_urls": [kf], "prompt": motion, "mode": "normal",
                     "duration": str(gen_dur), "resolution": vres, "aspect_ratio": aspect},
                    key, f"{sh['name']} grok {gen_dur}s")
        if c:
            download(c, clip)
        return sh["name"], c

    if pending:
        failed = []
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
            futs = [ex.submit(make_clip, sh, gd, cp) for sh, gd, cp in pending]
            for f in as_completed(futs):
                name, c = f.result()
                if not c:
                    failed.append(name)
        if failed:
            print(f"CLIPS FAILED: {failed} - rerun animate to retry"); sys.exit(1)

    # measure real speech ends so dialogue scenes finish before the cut
    measure_speech_ends([(n, p) for n, p, c, kb2, dlg in ordered if dlg], outdir, state)

    # edit: trim to cut lengths (keep audio so dialogue survives), concat
    print("Editing ...", flush=True)
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h},fps=24,format=yuv420p"
    trims = []
    for i, (name, path, cut, is_kb, is_dlg) in enumerate(ordered):
        if is_dlg:
            measured = state.get("speech_end", {}).get(name)
            if measured:
                dur = clip_seconds(path)
                cut = min(dur or cut, measured + SPEECH_TAIL)
        t = os.path.join(outdir, f"_trim{i:02d}.mp4")
        # kenburns clips are exact length; a dialogue take keeps its opening
        # frames (the line starts right away); silent grok skips the soft start
        args = ["-ss", "0" if (is_kb or is_dlg) else start, "-i", path, "-t", str(cut),
                "-map", "0:v:0", "-map", "0:a:0?",
                "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-ar", "48000"]
        # under a narrator, silent b-roll gets ducked HARD (grok ad-libs stray
        # lines); a dialogue take keeps full volume - the line IS the take
        if narr and not is_kb and not is_dlg:
            args += ["-af", f"volume={SILENT_CLIP_GAIN}"]
        run_ff(args + [t])
        trims.append(t)
    listp = os.path.join(outdir, "_concat.txt")
    with open(listp, "w") as f:
        for t in trims:
            f.write(f"file '{os.path.abspath(t)}'\n")
    final = os.path.join(outdir, "final.mp4")
    if narr:
        # per-clip levels were set at trim time (silent b-roll 0.06, dialogue
        # full); here the narrator just lays on top. normalize=0 so the bed
        # does not pump. duration=first keeps the video's length.
        pre = os.path.join(outdir, "_prefinal.mp4")
        run_ff(["-f", "concat", "-safe", "0", "-i", listp, "-c", "copy", pre])
        run_ff(["-i", pre, "-i", narr, "-filter_complex",
                "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-ar", "48000", final])
    else:
        run_ff(["-f", "concat", "-safe", "0", "-i", listp, "-c", "copy", final])
        if all(k for _, _, _, k, _ in ordered):
            print("NOTE: all shots are Ken Burns stills, so final.mp4 is silent - "
                  "set settings.narration_audio to a voiceover file and rerun animate.")

    for f in os.listdir(outdir):
        if f.startswith("_"):
            os.remove(os.path.join(outdir, f))
    proj = os.path.basename(os.path.abspath(outdir))
    dest = f"gdrive:clone-video/{proj}"
    try:
        subprocess.run(["rclone", "copy", outdir, dest], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
        print(f"saved to {dest}", flush=True)
    except Exception as e:
        print(f"Drive upload skipped ({e}); local assets in {outdir}", flush=True)
    print("=== DONE ===", flush=True)
    print(f"final: {final}", flush=True)


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "upload":
        upload(sys.argv[2])
    elif cmd == "estimate":
        estimate(json.load(open(sys.argv[2])))
    elif cmd == "sheet":
        sheet(sys.argv[2], sys.argv[3])
    elif cmd == "storyboard":
        storyboard(json.load(open(sys.argv[2])), sys.argv[3])
    elif cmd == "thumbnail":
        thumbnail(sys.argv[2], sys.argv[3])
    elif cmd == "animate":
        animate(json.load(open(sys.argv[2])), sys.argv[3])
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
