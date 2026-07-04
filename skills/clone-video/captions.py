#!/usr/bin/env python3
"""clone-video captions: clone the SOURCE's caption look onto the new video.

  captions.py align <audio_or_video> <words.json> [script.txt]   # whisper word timestamps (free, local);
                                                    # script.txt = the TRUE dialogue text - whisper then only
                                                    # supplies TIMING and the script supplies the words
                                                    # (whisper garbles non-English; the script never does)
  captions.py render <words.json> <capstyle.json> <capdir> [W H]  # caption PNGs + events.json
  captions.py burn <video> <capdir> <out.mp4>              # overlay the captions onto the video

PNG-overlay pipeline (not ASS/drawtext - the homebrew ffmpeg here lacks libass):
Pillow draws each caption screen (exact fonts, rounded pills, karaoke two-tone),
ffmpeg overlays each PNG during [start, end]. events.json in capdir carries the
schedule; burns run in batches so hundreds of captions do not blow one command.

capstyle.json comes from Phase 1 analysis (analysis/captions.json):
{
  "type": "karaoke_word | phrase_pop | box_phrase | static",
  "font": {"family": "Arial Rounded MT Bold", "size_frac": 0.06, "case": "as_is", "bold": true},
  "colors": {"base": "#111111", "highlight": "#FFD700", "stroke": "#000000", "box": "#FFD52E"},
  "stroke_width_frac": 0.006,
  "position": "bottom_center | middle_center | top_center",
  "words_per_screen": 5
}
karaoke_word = spoken word highlighted as it is said (one PNG per word state).
karaoke_box  = karaoke on a white bar: black words, the CURRENT word gets a
               yellow rounded highlight behind it as it is spoken (colors.box).
phrase_pop   = whole phrase appears on its start time.
box_phrase   = phrase on a filled rounded pill (colors.box) - the ESL yellow-pill look.
static       = phrase_pop with longer screens.
"""
import glob, json, math, os, subprocess, sys

GAP_BREAK = 0.6    # a pause longer than this starts a new caption screen
BURN_BATCH = 80    # overlays per ffmpeg pass

FONT_DIRS = ["/System/Library/Fonts/Supplemental", "/System/Library/Fonts",
             "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]


def _norm_word(w):
    import unicodedata
    w = unicodedata.normalize("NFD", w.lower())
    return "".join(c for c in w if c.isalnum())


def _script_align(heard, script_words):
    """Map the TRUE script words onto whisper's timings. Matched words take
    their heard timing; unmatched script words interpolate between anchors."""
    import difflib
    a = [_norm_word(w["w"]) for w in heard]
    b = [_norm_word(w) for w in script_words]
    out = [None] * len(script_words)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            out[blk.b + k] = {"w": script_words[blk.b + k],
                              "s": heard[blk.a + k]["s"], "e": heard[blk.a + k]["e"]}
    # fill gaps by interpolating between the nearest timed neighbors
    for i, w in enumerate(out):
        if w is not None:
            continue
        lo = next((j for j in range(i - 1, -1, -1) if out[j]), None)
        hi = next((j for j in range(i + 1, len(out)) if out[j]), None)
        t0 = out[lo]["e"] if lo is not None else (heard[0]["s"] if heard else 0.0)
        t1 = out[hi]["s"] if hi is not None else (heard[-1]["e"] if heard else t0 + 1)
        span_lo = lo if lo is not None else -1
        span_hi = hi if hi is not None else len(out)
        n = span_hi - span_lo - 1
        k = i - span_lo - 1
        step = max((t1 - t0) / max(n, 1), 0.12)
        out[i] = {"w": script_words[i], "s": round(t0 + k * step, 3),
                  "e": round(t0 + (k + 1) * step, 3)}
    return out


def align(media, out_json, script_path=None):
    import whisper
    model = whisper.load_model("base")
    result = model.transcribe(media, word_timestamps=True)
    words = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            t = w["word"].strip()
            if t:
                words.append({"w": t, "s": round(w["start"], 3), "e": round(w["end"], 3)})
    if script_path:
        script_words = open(script_path).read().split()
        matched = words
        words = _script_align(words, script_words)
        print(f"script-aligned: {len(script_words)} script words onto {len(matched)} heard words")
    with open(out_json, "w") as f:
        json.dump(words, f, indent=1)
    print(f"{len(words)} words -> {out_json}")


def _find_font(family, px):
    from PIL import ImageFont
    want = family.lower().replace(" ", "")
    for d in FONT_DIRS:
        for p in sorted(glob.glob(os.path.join(d, "*.tt[fc]")) + glob.glob(os.path.join(d, "*.otf"))):
            if want in os.path.basename(p).lower().replace(" ", ""):
                try:
                    return ImageFont.truetype(p, px)
                except OSError:
                    continue
    for fallback in ["Arial Bold.ttf", "Arial.ttf", "Helvetica.ttc"]:
        for d in FONT_DIRS:
            p = os.path.join(d, fallback)
            if os.path.exists(p):
                return ImageFont.truetype(p, px)
    return ImageFont.load_default(px)


def _screens(words, per_screen, style_type):
    if style_type == "static":
        per_screen = max(per_screen, 7)
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= per_screen or w["s"] - cur[-1]["e"] > GAP_BREAK
                    or cur[-1]["w"].rstrip().endswith((".", "!", "?"))):
            out.append(cur); cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def _draw_caption(texts, colors, font, stroke_w, stroke_col, box_col, pad,
                  hi_index=None, hi_col=None):
    """One caption image. texts = [(word, color)] drawn left to right.
    hi_index: word position that gets a rounded highlight (hi_col) behind it."""
    from PIL import Image, ImageDraw
    space = font.getbbox(" ")[2]
    widths = [font.getbbox(t)[2] for t, _ in texts]
    asc, desc = font.getmetrics()
    tw = sum(widths) + space * (len(texts) - 1)
    th = asc + desc
    w = tw + 2 * pad + 2 * stroke_w
    h = th + 2 * pad + 2 * stroke_w
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if box_col:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=box_col)
    x = pad + stroke_w
    for j, ((t, col), twd) in enumerate(zip(texts, widths)):
        if hi_index is not None and j == hi_index and hi_col:
            hp = max(3, pad // 3)
            d.rounded_rectangle([x - hp, pad + stroke_w - hp,
                                 x + twd + hp, pad + stroke_w + th + hp],
                                radius=(th + 2 * hp) // 4, fill=hi_col)
        d.text((x, pad + stroke_w), t, font=font, fill=col,
               stroke_width=0 if box_col else stroke_w, stroke_fill=stroke_col)
        x += twd + space
    return img


def render(words_json, style_json, capdir, w=1280, h=720):
    words = json.load(open(words_json))
    st = json.load(open(style_json))
    os.makedirs(capdir, exist_ok=True)
    font = _find_font(st.get("font", {}).get("family", "Arial Bold"),
                      int(h * float(st.get("font", {}).get("size_frac", 0.06))))
    colors = st.get("colors", {})
    stype = st.get("type", "box_phrase")
    base = colors.get("base", "#FFFFFF")
    hilite = colors.get("highlight", "#FFD700")
    stroke_col = colors.get("stroke", "#000000")
    box_col = colors.get("box", "#FFD52E") if stype == "box_phrase" else None
    if stype == "karaoke_box":
        box_col = colors.get("bar", "#FFFFFF")
    stroke_w = 0 if box_col else max(2, int(h * float(st.get("stroke_width_frac", 0.006))))
    pad = int(h * 0.018) if box_col else int(h * 0.006)
    upper = st.get("font", {}).get("case") == "upper"

    events, n = [], 0
    for scr in _screens(words, int(st.get("words_per_screen", 5)), stype):
        txts = [(wd["w"].upper() if upper else wd["w"]) for wd in scr]
        if stype == "karaoke_word":
            # one PNG per word state: words up to i shown in highlight
            for i, wd in enumerate(scr):
                img = _draw_caption([(t, hilite if j <= i else base) for j, t in enumerate(txts)],
                                    colors, font, stroke_w, stroke_col, box_col, pad)
                name = f"cap{n:04d}.png"; n += 1
                img.save(os.path.join(capdir, name))
                end = scr[i + 1]["s"] if i + 1 < len(scr) else wd["e"] + 0.15
                events.append({"png": name, "s": wd["s"], "e": round(end, 3)})
        elif stype == "karaoke_box":
            # black words on a bar; the word being SPOKEN gets a yellow
            # rounded highlight behind it (one PNG per word state)
            for i, wd in enumerate(scr):
                img = _draw_caption([(t, base) for t in txts], colors, font,
                                    stroke_w, stroke_col, box_col, pad,
                                    hi_index=i, hi_col=hilite)
                name = f"cap{n:04d}.png"; n += 1
                img.save(os.path.join(capdir, name))
                end = scr[i + 1]["s"] if i + 1 < len(scr) else wd["e"] + 0.15
                events.append({"png": name, "s": wd["s"], "e": round(end, 3)})
        else:
            img = _draw_caption([(t, base) for t in txts],
                                colors, font, stroke_w, stroke_col, box_col, pad)
            name = f"cap{n:04d}.png"; n += 1
            img.save(os.path.join(capdir, name))
            events.append({"png": name, "s": scr[0]["s"], "e": round(scr[-1]["e"] + 0.15, 3)})
    meta = {"position": st.get("position", "bottom_center"), "events": events,
            "res": [w, h]}
    with open(os.path.join(capdir, "events.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print(f"{len(events)} caption images ({stype}) -> {capdir}")


def _y_expr(position):
    return {"bottom_center": "main_h-overlay_h-main_h*0.06",
            "middle_center": "(main_h-overlay_h)/2",
            "top_center": "main_h*0.06"}.get(position, "main_h-overlay_h-main_h*0.06")


def burn(video, capdir, out):
    meta = json.load(open(os.path.join(capdir, "events.json")))
    events = meta["events"]
    y = _y_expr(meta.get("position", "bottom_center"))
    src = video
    for b in range(0, max(len(events), 1), BURN_BATCH):
        batch = events[b:b + BURN_BATCH]
        if not batch:
            break
        last = b + BURN_BATCH >= len(events)
        dst = out if last else os.path.join(capdir, f"_pass{b // BURN_BATCH}.mp4")
        cmd = ["ffmpeg", "-y", "-i", src]
        for ev in batch:
            cmd += ["-i", os.path.join(capdir, ev["png"])]
        parts, cur = [], "0:v"
        for i, ev in enumerate(batch):
            nxt = f"v{i}"
            parts.append(f"[{cur}][{i + 1}:v]overlay=x=(main_w-overlay_w)/2:y={y}"
                         f":enable='between(t,{ev['s']},{ev['e']})'[{nxt}]")
            cur = nxt
        cmd += ["-filter_complex", ";".join(parts), "-map", f"[{cur}]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy", dst]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        src = dst
    for p in glob.glob(os.path.join(capdir, "_pass*.mp4")):
        if p != out:
            os.remove(p)
    print(f"burned {len(events)} captions -> {out}")


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "align":
        align(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
    elif cmd == "render":
        w, h = (int(sys.argv[5]), int(sys.argv[6])) if len(sys.argv) > 6 else (1280, 720)
        render(sys.argv[2], sys.argv[3], sys.argv[4], w, h)
    elif cmd == "burn":
        burn(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
