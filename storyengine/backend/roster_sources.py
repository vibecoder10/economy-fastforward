"""Small directly retrieved archive packet for the carrier coverage reviewer.

Only server-owned source URLs are fetched; generated source links never become
network targets. Failed fetches are reported as unavailable, never as evidence.
"""
import asyncio
import hashlib
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

SCOPE_SOURCES = (
    ("https://www.royalnavyresearcharchive.org.uk/ESCORT_2/CLASSES.htm", "Ships built to the same design"),
    ("https://www.rmg.co.uk/collections/objects/rmgc-object-1128690", "Specification (hull - general)"),
    ("https://www.rmg.co.uk/collections/objects/rmgc-object-1149265", "Implacable"),
)


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head", "nav", "footer"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head", "nav", "footer"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def source_excerpt(html, anchor):
    parser = _VisibleText()
    parser.feed(html)
    text = " ".join(" ".join(parser.parts).split())
    start = text.casefold().find(anchor.casefold())
    # A 200 login/challenge/error page is not an archive document.
    if start < 0:
        return ""
    return text[max(0, start - 100):start + 7000]


async def fetch_scope_sources():
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        async def fetch_one(url, anchor):
            try:
                data = bytearray()
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    if "text/html" not in response.headers.get("content-type", "").lower():
                        return {"url": url, "available": False}
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 512_000:
                            return {"url": url, "available": False}
                excerpt = source_excerpt(data.decode("utf-8", errors="replace"), anchor)
                if len(excerpt) < 100:
                    return {"url": url, "available": False}
                return {"url": url, "available": True, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "sha256": hashlib.sha256(data).hexdigest(), "excerpt": excerpt}
            except (httpx.HTTPError, ValueError):
                return {"url": url, "available": False}
        return await asyncio.gather(*(fetch_one(url, anchor) for url, anchor in SCOPE_SOURCES))
