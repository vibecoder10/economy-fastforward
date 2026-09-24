"""Offline measuring run: fetch each cited page, find the quote, cut a passage around it."""
import asyncio, json, re, unicodedata, difflib
from html.parser import HTMLParser
import httpx

HALF = 250  # ~500-char passage
SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "svg", "form", "aside"}
BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "tr", "td", "th", "section", "article", "table", "dd", "dt", "blockquote"}


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS: self.skip += 1
        if tag in BLOCK: self.out.append("\n")
    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip: self.skip -= 1
        if tag in BLOCK: self.out.append("\n")
    def handle_data(self, d):
        if not self.skip: self.out.append(d)


def page_text(html):
    t = Text(); t.feed(html)
    s = "".join(t.out)
    s = re.sub(r"[ \t\r\f\v\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def norm(s):
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).lower()


def strip_prefix(q):
    return re.sub(r"^Regarding [^:]{1,80}: ", "", q.strip())


def locate(text, quote):
    """Return (start,end,method) of the quote in text, working on a normalized copy with an index map."""
    chars, idx = [], []
    prev_space = False
    raw = unicodedata.normalize("NFKC", text)
    for i, ch in enumerate(raw):
        c = norm(ch) if not ch.isspace() else " "
        if c == " ":
            if prev_space: continue
            prev_space = True
        else:
            prev_space = False
        for cc in c:
            chars.append(cc); idx.append(i)
    nt = "".join(chars)
    q = norm(quote).strip(" .\"'")
    pos = nt.find(q)
    if pos >= 0:
        return idx[pos], idx[min(pos + len(q), len(idx) - 1)], raw, "exact"
    # anchor on first/last 40 chars (quotes with ellipses or small edits)
    for L in (60, 40, 25):
        if len(q) < L * 2: continue
        a, b = nt.find(q[:L]), nt.find(q[-L:])
        if a >= 0 and b >= a and b - a < len(q) * 2:
            return idx[a], idx[min(b + L, len(idx) - 1)], raw, "anchors"
        if a >= 0:
            return idx[a], idx[min(a + len(q), len(idx) - 1)], raw, "head-anchor"
        if b >= 0:
            s = max(0, b + L - len(q))
            return idx[s], idx[min(b + L, len(idx) - 1)], raw, "tail-anchor"
    # fuzzy: best matching window by longest block
    sm = difflib.SequenceMatcher(None, nt, q, autojunk=False)
    m = sm.find_longest_match(0, len(nt), 0, len(q))
    if m.size >= max(30, len(q) * 0.5):
        s = max(0, m.a - m.b)
        return idx[s], idx[min(s + len(q), len(idx) - 1)], raw, f"fuzzy{m.size}/{len(q)}"
    return None


def cut(raw, s, e):
    a, b = max(0, s - HALF), min(len(raw), e + HALF)
    # widen to sentence edges when close
    left = raw.rfind(". ", max(0, a - 120), s)
    if left >= 0 and left < a + 120: a = left + 2
    right = raw.find(". ", e, min(len(raw), b + 120))
    if right >= 0: b = right + 1
    return raw[a:b].strip()


UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}


async def fetch(client, url, sem):
    async with sem:
        try:
            r = await client.get(url, timeout=25)
            ct = r.headers.get("content-type", "")
            if r.status_code != 200:
                return url, {"ok": False, "why": f"http {r.status_code}"}
            if "pdf" in ct:
                return url, {"ok": False, "why": "pdf"}
            return url, {"ok": True, "text": page_text(r.text)}
        except Exception as ex:
            return url, {"ok": False, "why": type(ex).__name__}


async def main():
    p = json.load(open("pk.json"))
    urls = sorted({e["source_url"] for m in p.values() for c in m["claim_assessment"]["claims"] for e in c["evidence"]})
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(headers=UA, follow_redirects=True) as cl:
        pages = dict(await asyncio.gather(*(fetch(cl, u, sem) for u in urls)))
    rows = []
    for key, m in p.items():
        for c in m["claim_assessment"]["claims"]:
            for e in c["evidence"]:
                q = strip_prefix(e["quote"])
                pg = pages[e["source_url"]]
                row = {"machine": m["machine"], "claim_id": c["id"], "claim": c["claim"], "quote": q,
                       "url": e["source_url"], "page_ok": pg["ok"], "why": pg.get("why")}
                if pg["ok"]:
                    hit = locate(pg["text"], q)
                    if hit:
                        s, en, raw, how = hit
                        row.update(found=True, how=how, passage=cut(raw, s, en))
                    else:
                        row.update(found=False)
                rows.append(row)
    json.dump({"pages": {u: {k: v for k, v in pg.items() if k != "text"} | {"chars": len(pg.get("text", ""))} for u, pg in pages.items()},
               "rows": rows}, open("measure.json", "w"), indent=1)
    json.dump({u: pg.get("text", "") for u, pg in pages.items()}, open("pages.json", "w"))
    ok = sum(pg["ok"] for pg in pages.values())
    print(f"pages {ok}/{len(pages)} loaded")
    from collections import Counter
    print(Counter(pg.get("why") for pg in pages.values() if not pg["ok"]))
    loaded = [r for r in rows if r["page_ok"]]
    found = [r for r in loaded if r.get("found")]
    print(f"quotes {len(rows)}; on loaded pages {len(loaded)}; quote found {len(found)}")
    print(Counter(r["how"].rstrip("0123456789/") for r in found))
    sizes = sorted(len(r["passage"]) for r in found)
    if sizes: print("passage chars min/med/max", sizes[0], sizes[len(sizes)//2], sizes[-1])


asyncio.run(main())
