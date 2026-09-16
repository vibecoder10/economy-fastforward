"""Bounded Wikipedia article evidence for reference-image selection."""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import unquote, urljoin, urlparse

import httpx

from static_docu import _WIKIPEDIA_API, _COMMONS_UA, _url_file_title, _wm_get

MAX_ARTICLES = 4
MAX_PAGE_TEXT = 18_000


def _classes(attrs: dict[str, str]) -> set[str]:
    return set((attrs.get("class") or "").lower().split())


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent=None):
        self.tag, self.attrs, self.parent = tag, attrs, parent
        self.children: list[_Node] = []
        self.parts: list[str | _Node] = []

    def text(self) -> str:
        return " ".join(" ".join(part if isinstance(part, str) else part.text()
                                  for part in self.parts).split())

    def descendants(self, tag: str | None = None):
        for child in self.children:
            if tag is None or child.tag == tag:
                yield child
            yield from child.descendants(tag)


class _ArticleHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = _Node("root", {})
        self.stack = [self.root]
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        node = _Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        self.stack[-1].parts.append(node)
        if tag in {"script", "style"}:
            self.skip += 1
        if tag not in {"img", "br", "meta", "link", "input", "hr", "source", "area", "base", "embed", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in {"img", "br", "meta", "link", "input", "hr", "source", "area", "base", "embed", "wbr"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not self.skip:
            self.stack[-1].parts.append(data)


def _article_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")


def _image_title(img: _Node, base_url: str) -> str | None:
    parent = img.parent
    while parent:
        if parent.tag == "a":
            href = unquote(parent.attrs.get("href") or "")
            found = re.search(r"/wiki/File:([^?#]+)", href, re.I)
            if found:
                return "File:" + found.group(1).replace("_", " ")
        parent = parent.parent
    filename = _url_file_title(urljoin(base_url, img.attrs.get("src") or ""))
    return "File:" + filename.replace("_", " ") if filename else None


def _caption_for_image(img: _Node) -> str:
    # Modern MediaWiki figures bind exactly one figcaption to their image.
    node = img.parent
    while node:
        if node.tag == "figure":
            return next((child.text() for child in node.descendants("figcaption") if child.text()), "")
        classes = _classes(node.attrs)
        # Legacy thumbnail markup has a caption in the same thumb container.
        if "thumb" in classes:
            return next((child.text() for child in node.descendants()
                         if "thumbcaption" in _classes(child.attrs) and child.text()), "")
        if node.tag == "td" and "infobox-image" in _classes(node.attrs):
            own = next((child.text() for child in node.descendants()
                        if ({"imagecaption", "infobox-caption"} & _classes(child.attrs)) and child.text()), "")
            if own:
                return own
            row = node.parent
            if row and row.tag == "tr" and row.parent:
                rows = [child for child in row.parent.children if child.tag == "tr"]
                try:
                    following = rows[rows.index(row) + 1]
                except (ValueError, IndexError):
                    following = None
                if following:
                    if "infobox-caption" in _classes(following.attrs):
                        return following.text()
                    caption_cell = next((child for child in following.descendants("td")
                                         if "infobox-caption" in _classes(child.attrs)), None)
                    if caption_cell:
                        return caption_cell.text()
        node = node.parent
    return ""


def _is_decorative(title: str, img: _Node) -> bool:
    words = " ".join((title or "", img.attrs.get("alt") or "", img.attrs.get("class") or "")).lower()
    return any(word in words for word in ("flag", "icon", "logo"))


def _parse_article(html: str, page_url: str, context: str) -> list[dict]:
    parser = _ArticleHTML()
    parser.feed(html or "")
    candidates, seen = [], set()
    for img in parser.root.descendants("img"):
        source = urljoin(page_url, img.attrs.get("src") or "")
        if source.startswith("//"):
            source = "https:" + source
        if not source:
            continue
        title = _image_title(img, page_url)
        caption = _caption_for_image(img)
        key = (title or source).casefold()
        if not title or not caption or key in seen or _is_decorative(title, img):
            continue
        seen.add(key)
        candidates.append({
            "image_url": source,
            "source_page": page_url,
            "title": title,
            "caption": caption,
            "evidence": [
                {"url": page_url, "text": caption, "kind": "image_caption"},
                {"url": page_url, "text": context, "kind": "article_context"},
            ],
        })
    return candidates


async def article_pack(titles: list[str]) -> dict:
    """Return bounded Wikipedia context and only captions tied to real images."""
    context, images, seen_titles = [], [], set()
    requested = []
    for title in titles:
        title = str(title or "").strip()
        if title and title.casefold() not in seen_titles and len(requested) < MAX_ARTICLES:
            seen_titles.add(title.casefold())
            requested.append(title)
    if not requested:
        return {"context": context, "images": images}
    try:
        async with httpx.AsyncClient(timeout=30, headers=_COMMONS_UA) as client:
            for title in requested:
                try:
                    response = await _wm_get(client, _WIKIPEDIA_API, params={
                        "action": "parse", "page": title, "redirects": 1,
                        "prop": "text|wikitext", "format": "json",
                    })
                    response.raise_for_status()
                    parsed = response.json().get("parse") or {}
                    actual_title = str(parsed.get("title") or title)
                    page_url = _article_url(actual_title)
                    text = parsed.get("text") or ""
                    if isinstance(text, dict):
                        text = text.get("*") or ""
                    visible = _ArticleHTML(); visible.feed(str(text))
                    article_context = visible.root.text()[:MAX_PAGE_TEXT]
                    if article_context:
                        context.append({"url": page_url, "text": article_context, "kind": "article_context"})
                    images.extend(_parse_article(str(text), page_url, article_context))
                except Exception:
                    continue
    except Exception:
        return {"context": [], "images": []}
    return {"context": context, "images": images}
