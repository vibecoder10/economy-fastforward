#!/usr/bin/env python3
"""clone-video fetch: pull everything needed to analyze a YouTube video, locally.

  fetch.py <youtube_url> <outdir>

Downloads into <outdir>/source/: the video (720p cap), thumbnail.png, info.json
(title, channel, views, duration), transcript.txt (from subs), and 6 evenly
spaced frames (frame_1.png .. frame_6.png) for style analysis.
Runs on this Mac on purpose: the VPS IP is bot-blocked by YouTube, the laptop is not.
No API cost.
"""
import glob, json, os, re, subprocess, sys


def vtt_to_text(path):
    lines, last = [], None
    for raw in open(path, encoding="utf-8", errors="replace"):
        line = re.sub(r"<[^>]+>", "", raw).strip()
        if (not line or "-->" in line or line == "WEBVTT" or
                line.startswith(("Kind:", "Language:", "NOTE")) or line.isdigit()):
            continue
        if line != last:
            lines.append(line)
            last = line
    return "\n".join(lines)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    url, outdir = sys.argv[1], sys.argv[2]
    src = os.path.join(outdir, "source")
    os.makedirs(src, exist_ok=True)

    # check=False: a failed subtitle download must not kill the fetch;
    # we verify the pieces we actually need below.
    subprocess.run([
        "yt-dlp", "-f", "bv*[height<=720]+ba/b[height<=720]/b",
        "--write-info-json", "--write-thumbnail", "--convert-thumbnails", "png",
        "--write-auto-subs", "--write-subs", "--sub-langs", "en",
        "--merge-output-format", "mp4",
        "-o", os.path.join(src, "video.%(ext)s"), url,
    ], check=False)

    infos = glob.glob(os.path.join(src, "*.info.json"))
    if not infos:
        print("ERROR: fetch failed (no info.json). If age/region gated, retry with "
              "--cookies-from-browser chrome added to the yt-dlp command.", file=sys.stderr)
        sys.exit(1)
    info_path = infos[0]
    info = json.load(open(info_path))

    # normalize thumbnail name
    thumbs = [p for p in glob.glob(os.path.join(src, "video.png"))] or \
             [p for p in glob.glob(os.path.join(src, "*.png")) if "frame_" not in p]
    thumb = None
    if thumbs:
        thumb = os.path.join(src, "thumbnail.png")
        if thumbs[0] != thumb:
            os.replace(thumbs[0], thumb)

    # transcript from whichever subs file landed
    transcript = None
    vtts = glob.glob(os.path.join(src, "*.vtt")) + glob.glob(os.path.join(src, "*.srt"))
    if vtts:
        transcript = os.path.join(src, "transcript.txt")
        with open(transcript, "w") as f:
            f.write(vtt_to_text(vtts[0]))

    # 6 evenly spaced frames for style analysis
    video = os.path.join(src, "video.mp4")
    frames = []
    dur = info.get("duration") or 0
    if os.path.exists(video) and dur:
        for i, frac in enumerate([0.10, 0.25, 0.40, 0.55, 0.70, 0.85], 1):
            fp = os.path.join(src, f"frame_{i}.png")
            subprocess.run(["ffmpeg", "-y", "-ss", str(int(dur * frac)), "-i", video,
                            "-frames:v", "1", fp],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            frames.append(fp)

    print(json.dumps({
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "duration_sec": dur,
        "views": info.get("view_count"),
        "upload_date": info.get("upload_date"),
        "video": video if os.path.exists(video) else None,
        "thumbnail": thumb,
        "transcript": transcript,
        "frames": frames,
        "info_json": info_path,
    }, indent=2))


if __name__ == "__main__":
    main()
