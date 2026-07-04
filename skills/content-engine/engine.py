#!/usr/bin/env python3
"""content-engine: topic+seed -> cast sheet -> per-beat coverage keyframes (GPT Image 2)
-> grok-imagine clips -> trim + stitch. Beats show one moment from several angles so cuts
read as coverage, not jumps. In-beat angles are generated off the beat's master frame so
they match. Optional per-shot `dialogue` (grok speaks it, lip-synced).

  engine.py estimate <spec.json>
  engine.py run <spec.json> <outdir>
  engine.py upload <local_image>     # host a local seed so kie.ai can fetch it

Reads KIE_AI_API_KEY from ~/economy-fastforward/.env. Cost is grok-dominated, ~$0.14/shot.
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error, urllib.parse

ENV_PATHS = [os.path.expanduser("~/economy-fastforward/.env"),
             os.path.expanduser("~/economy-fastforward/storyengine/backend/.env")]
CREATE = "https://api.kie.ai/api/v1/jobs/createTask"
RECORD = "https://api.kie.ai/api/v1/jobs/recordInfo"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
CREDIT = 0.005  # USD per kie.ai credit


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


def upload(path):  # local seed -> public URL (GPT Image 2 reads catbox fine)
    out = subprocess.run(["curl", "-fsS", "-A", UA, "-F", "reqtype=fileupload",
        "-F", f"fileToUpload=@{path}", "https://catbox.moe/user/api.php"],
        capture_output=True, text=True, timeout=120)
    if out.stdout.strip().startswith("http"):
        print(out.stdout.strip()); return out.stdout.strip()
    print(f"ERROR upload: {out.stderr}", file=sys.stderr); sys.exit(1)


def target_wh(res, aspect):  # ponytail: 16:9/9:16 only; other ratios -> edit this
    base = {"480p": 480, "720p": 720, "1080p": 1080}.get(res, 720)
    long = (base * 16 // 9) // 2 * 2
    return (base, long) if aspect == "9:16" else (long, base)


def run_ff(args):
    subprocess.run(["ffmpeg", "-y", *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def shots_of(spec):
    return [s for beat in spec["beats"] for s in beat]


def estimate(spec):
    n = len(shots_of(spec))
    seed = spec.get("settings", {}).get("animator") == "seedance"
    per = 10 + (60 if seed else 18)  # keyframe + animator clip (seedance ~$0.30/6s vs grok $0.09)
    credits = 10 + n * per
    print(json.dumps({"shots": n, "animator": "seedance" if seed else "grok",
                      "credits": credits, "est_total_usd": round(credits * CREDIT, 2),
                      "note": "seedance ~$0.40/shot, grok ~$0.14/shot. Confirm rates in your kie.ai dashboard."}, indent=2))


def run(spec, outdir):
    key = load_key()
    if not key:
        print("ERROR: KIE_AI_API_KEY not found"); sys.exit(1)
    os.makedirs(outdir, exist_ok=True)
    s = spec.get("settings", {})
    aspect = s.get("aspect_ratio", "16:9")
    vres = s.get("video_resolution", "720p")
    rres = s.get("ref_resolution", "2K")
    start = str(s.get("start_offset", "0.8"))
    animator = s.get("animator", "grok")  # "grok" (cheap) or "seedance" (expensive, smoother)
    seeds = spec.get("seed_urls") or []

    # 1. cast sheet
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
    download(cast, os.path.join(outdir, "0_cast_sheet.png"))

    # 2. beats: master keyframe -> angle keyframes (anchored on master) -> grok clip per shot
    ordered = []  # (clip_path, cut)
    for beat in spec["beats"]:
        if all(os.path.exists(os.path.join(outdir, sh["name"] + "_clip.mp4")) for sh in beat):
            for sh in beat:
                ordered.append((os.path.join(outdir, sh["name"] + "_clip.mp4"), sh["cut"]))
            print(f"[skip] beat {beat[0]['name']} done"); continue
        master = beat[0]
        mk = gen("gpt-image-2-image-to-image",
                 {"prompt": master["image"], "input_urls": [cast], "aspect_ratio": aspect, "resolution": rres},
                 key, master["name"] + " kf*")
        if not mk:
            sys.exit(1)
        download(mk, os.path.join(outdir, master["name"] + "_kf.png"))
        master["kf"] = mk
        for sh in beat[1:]:
            k = gen("gpt-image-2-image-to-image",
                    {"prompt": sh["image"] + " Match the lighting, wardrobe and setting of the attached reference; only the camera angle changes.",
                     "input_urls": [cast, mk], "aspect_ratio": aspect, "resolution": rres},
                    key, sh["name"] + " kf")
            if not k:
                sys.exit(1)
            download(k, os.path.join(outdir, sh["name"] + "_kf.png"))
            sh["kf"] = k
        for sh in beat:
            motion = sh["motion"]
            if sh.get("dialogue"):
                motion += f' The character speaks, lip-synced, saying: "{sh["dialogue"]}"'
            if animator == "seedance":
                c = gen("bytedance/seedance-2-fast",
                        {"prompt": motion, "first_frame_url": sh["kf"], "reference_image_urls": [cast],
                         "aspect_ratio": aspect, "resolution": vres, "duration": 6, "generate_audio": True},
                        key, sh["name"] + " seedance")
            else:
                c = gen("grok-imagine/image-to-video",
                        {"image_urls": [sh["kf"]], "prompt": motion, "mode": "normal",
                         "duration": "6", "resolution": vres, "aspect_ratio": aspect},
                        key, sh["name"] + " grok")
            if not c:
                sys.exit(1)
            ordered.append((download(c, os.path.join(outdir, sh["name"] + "_clip.mp4")), sh["cut"]))

    # 3. edit: trim each clip to its cut length (keep audio so dialogue survives), concat
    print("Editing ...", flush=True)
    w, h = target_wh(vres, aspect)
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h},fps=24,format=yuv420p"
    trims = []
    for i, (path, cut) in enumerate(ordered):
        t = os.path.join(outdir, f"_trim{i:02d}.mp4")
        run_ff(["-ss", start, "-i", path, "-t", str(cut), "-map", "0:v:0", "-map", "0:a:0?",
                "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-ar", "48000", t])
        trims.append(t)
    listp = os.path.join(outdir, "_concat.txt")
    with open(listp, "w") as f:
        for t in trims:
            f.write(f"file '{os.path.abspath(t)}'\n")
    final = os.path.join(outdir, "final.mp4")
    run_ff(["-f", "concat", "-safe", "0", "-i", listp, "-c", "copy", final])

    # drop edit temps, then persist the real assets to Drive (best-effort; local is source of truth)
    for f in os.listdir(outdir):
        if f.startswith("_"):
            os.remove(os.path.join(outdir, f))
    proj = os.path.basename(outdir.rstrip("/"))
    dest = f"gdrive:content-engine/{proj}"
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
    elif cmd == "run":
        run(json.load(open(sys.argv[2])), sys.argv[3])
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
