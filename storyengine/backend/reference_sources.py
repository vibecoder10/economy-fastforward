"""Bounded public-source metadata collection; no pixels, models, or DB writes."""
from __future__ import annotations

import html.parser
import re
from typing import Any
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import httpx
from static_docu import (_COMMONS_API, _COMMONS_UA, _WIKIPEDIA_API,
    _api_issued_thumbs_batch, _gather_reference_candidates, _url_file_title,
    _wm_get, find_commons_photos)

MAX_CANDIDATES, MAX_PAGE_BYTES, MAX_PAGE_TEXT = 12, 250_000, 18_000

def _norm(url: str) -> str:
    p = urlparse(str(url or ""))
    return urlunparse((p.scheme.lower(), p.netloc.lower(), unquote(p.path), p.params, p.query, ""))

def _file(title: str) -> str:
    title = str(title or "").strip()
    if not title.lower().startswith("file:"): title = "File:" + title
    return "File:" + title[5:].replace("_", " ").strip()

def _commons_title(url: str) -> str | None:
    p = urlparse(str(url or "")); host, path = p.netloc.lower(), unquote(p.path)
    if not (host == "wikimedia.org" or host.endswith(".wikimedia.org") or host == "wikipedia.org" or host.endswith(".wikipedia.org")): return None
    if host in {"upload.wikimedia.org", "thumb.wikimedia.org"}:
        return _file(_url_file_title(url)) if _url_file_title(url) else None
    m = re.search(r"/wiki/Special:FilePath/(.+)$", path, re.I) or re.search(r"/wiki/(File:.+)$", path, re.I)
    return _file(m.group(1)) if m else None

def _names(machine: str, aliases: Any) -> list[str]:
    out, seen = [], set()
    for raw in list(aliases or []) + [machine]:
        value = str(raw or "").strip()
        if len(re.findall(r"[A-Za-z]", value)) >= 3 and value.casefold() not in seen:
            out.append(value); seen.add(value.casefold())
    return out

def _candidate(url: str, *, source_page: str | None = None, title="", caption="", width=None, height=None, evidence=None, reason_code=None, reason=None) -> dict:
    out = {"id":"", "image_url":url, "source_page":source_page or url, "title":title, "caption":caption,
           "width":width, "height":height, "evidence":evidence or []}
    if reason_code: out.update(reason_code=reason_code, reason=reason or reason_code)
    return out

class _VisibleHTML(html.parser.HTMLParser):
    def __init__(self): super().__init__(); self.text=[]; self.images=[]; self._skip=0
    def handle_starttag(self, tag, attrs):
        if tag in {"script","style"}: self._skip += 1
        if tag in {"img","a"}:
            value=dict(attrs).get("src" if tag == "img" else "href")
            if value: self.images.append(value)
    def handle_endtag(self, tag):
        if tag in {"script","style"}: self._skip=max(0,self._skip-1)
    def handle_data(self, data):
        if not self._skip: self.text.append(data)

def _text(value: object) -> str:
    parser = _VisibleHTML(); parser.feed(str(value or "")); return " ".join(" ".join(parser.text).split())

def _resolve(title: str, changes: dict[str,str]) -> str:
    seen=set(); title=_file(title)
    while title in changes and title not in seen: seen.add(title); title=changes[title]
    return title

async def _commons_metadata(urls: list[str]) -> dict[str,dict]:
    """One imageinfo query; maps every original Wikimedia input to its record."""
    asked: dict[str,list[str]]={}
    for url in urls:
        title=_commons_title(url)
        if title: asked.setdefault(title,[]).append(url)
    if not asked: return {}
    try:
        async with httpx.AsyncClient(timeout=30,headers=_COMMONS_UA) as client:
            response=await _wm_get(client,_COMMONS_API,params={"action":"query","titles":"|".join(asked),"redirects":1,"normalized":1,"prop":"imageinfo","iiprop":"url|size|extmetadata","iiurlwidth":1536,"format":"json"})
            response.raise_for_status(); query=response.json().get("query") or {}
            changes={}
            for row in (query.get("normalized") or [])+(query.get("redirects") or []):
                if row.get("from") and row.get("to"): changes[_file(row["from"])] = _file(row["to"])
            infos = [info for page in (query.get("pages") or {}).values() for info in page.get("imageinfo", [])]
            raw = [info["url"] for info in infos if info.get("url") and
                   (not info.get("thumburl") or info.get("thumburl") == info["url"])]
            issued=await _api_issued_thumbs_batch(client,raw) if raw else {}
    except Exception as exc:
        raise RuntimeError("metadata_unavailable") from exc
    pages={_file(page.get("title")):page for page in (query.get("pages") or {}).values() if page.get("title")}
    output={}
    for title, originals in asked.items():
        page=pages.get(_resolve(title,changes)); infos=(page or {}).get("imageinfo") or []
        if not infos: continue
        info=infos[0]; meta=info.get("extmetadata") or {}
        desc=info.get("descriptionurl") or "https://commons.wikimedia.org/wiki/"+(page.get("title") or title).replace(" ","_")
        caption=_text((meta.get("ImageDescription") or {}).get("value")); facts=[]
        for key in ("Source","Credit","DateTimeOriginal"):
            value=_text((meta.get(key) or {}).get("value"))
            if value: facts.append(f"{key}: {value}")
        evidence=[]
        if caption: evidence.append({"url":desc,"text":caption[:MAX_PAGE_TEXT],"kind":"image_caption"})
        if facts: evidence.append({"url":desc,"text":"\n".join(facts)[:MAX_PAGE_TEXT],"kind":"source_attribution"})
        for original in originals:
            thumb = info.get("thumburl")
            if not thumb or thumb == info.get("url"):
                thumb = issued.get(info.get("url"))
            image = original if "/thumb/" in urlparse(original).path else thumb
            # Raw upload links can 403.  Do not advertise one if no API thumbnail was issued.
            if not image or ("/thumb/" not in urlparse(image).path and "/thumb/" not in urlparse(original).path): continue
            output[_norm(original)]={"image_url":image,"source_page":desc,"title":page.get("title") or title,"caption":caption,"width":info.get("width"),"height":info.get("height"),"evidence":evidence}
    return output

async def _fetch_source_page(url: str, image_url: str) -> tuple[list[dict],str|None,str|None]:
    try:
        async with httpx.AsyncClient(timeout=30,follow_redirects=True,headers={"User-Agent":"StoryEngineReferenceSelection/1.0"}) as client:
            response=await client.get(url); response.raise_for_status(); raw=response.content[:MAX_PAGE_BYTES]
        parser=_VisibleHTML(); parser.feed(raw.decode("utf-8","ignore")); linked={_norm(urljoin(url,item)) for item in parser.images}
        if _norm(image_url) not in linked: return [],"source_link_missing","Source page does not link the supplied image."
        text=" ".join(" ".join(parser.text).split())[:MAX_PAGE_TEXT]
        return ([{"url":url,"text":text,"kind":"image_caption"}] if text else []),None,None
    except Exception as exc: return [],"source_unavailable",str(exc)[:240]

async def _wiki_context(names: list[str]) -> list[dict]:
    evidence=[]
    for name in names[:3]:
        try:
            async with httpx.AsyncClient(timeout=30,headers=_COMMONS_UA) as client:
                response=await _wm_get(client,_WIKIPEDIA_API,params={"action":"query","titles":name,"redirects":1,"prop":"revisions","rvprop":"content","rvslots":"main","format":"json"})
                response.raise_for_status(); pages=(response.json().get("query") or {}).get("pages") or {}
            for page in pages.values():
                revision=(page.get("revisions") or [{}])[0]; text=((revision.get("slots") or {}).get("main") or {}).get("*") or revision.get("*") or ""
                if text: evidence.append({"url":"https://en.wikipedia.org/wiki/"+str(page.get("title") or name).replace(" ","_"),"text":str(text)[:MAX_PAGE_TEXT],"kind":"article_context"})
        except Exception: continue
    return evidence

def _merge(base: dict, record: dict|None, context: list[dict], code=None, reason=None, page_evidence=None) -> dict:
    record=record or {}
    return _candidate(record.get("image_url") or base["image_url"],source_page=record.get("source_page") or base.get("source_page"),title=record.get("title", ""),caption=record.get("caption", ""),width=record.get("width"),height=record.get("height"),evidence=(record.get("evidence") or [])+(page_evidence or [])+context,reason_code=code,reason=reason)

def _search_queries(names: list[str], facts: dict | None) -> list[str]:
    role = str((facts or {}).get("role") or "").lower()
    category = next((kind for kind in ("submarine", "aircraft", "helicopter", "tank") if kind in role), "")
    if not category and any(kind in role for kind in ("bomber", "fighter")):
        category = "aircraft"
    # Class names can be shared by unrelated kinds of machine. Use the saved
    # roster's role to disambiguate discovery; this is never identity evidence.
    return [" ".join((re.sub(r"\bclass\b", "", name, flags=re.I) + " " + category).split())
            if category and category not in name.lower() else name for name in names[:2]]


async def collect_candidates(machine: str, aliases=None, *, facts=None, manual_url=None, source_page_url=None, cached_url=None) -> list[dict]:
    """Return metadata candidates; manual mode contains only the supplied image as c1."""
    names=_names(machine,aliases)
    if manual_url:
        if re.search(r"(?:^|[./])(google|bing|duckduckgo)\.|[?&]q=|/search",manual_url,re.I):
            result=_candidate(manual_url,reason_code="search_result_url",reason="Paste a direct image URL, not a search-results page."); result["id"]="c1"; return [result]
        context=await _wiki_context(names[:3])
        page_evidence,code,reason=([],None,None)
        if source_page_url: page_evidence,code,reason=await _fetch_source_page(source_page_url,manual_url)
        try: metadata=await _commons_metadata([manual_url])
        except RuntimeError: metadata={}; code,reason=code or "metadata_unavailable",reason or "Wikimedia metadata was unavailable."
        result=_merge({"image_url":manual_url,"source_page":source_page_url or manual_url},metadata.get(_norm(manual_url)),context,code,reason,page_evidence); result["id"]="c1"; return [result]
    context=await _wiki_context(names[:3])
    urls=[]; seen=set()
    def add(url):
        if not url or len(urls)>=MAX_CANDIDATES or _norm(url) in seen: return False
        seen.add(_norm(url)); urls.append(url); return True
    add(cached_url)
    for url,_ in await _gather_reference_candidates(machine,aliases,machine): add(url)
    for query in _search_queries(names, facts):
        if len(urls)>=MAX_CANDIDATES: break
        for row in await find_commons_photos(query,limit=4): add(row.get("url"))
    try: metadata=await _commons_metadata(urls); failed=False
    except RuntimeError: metadata={}; failed=True
    output=[]
    for index,url in enumerate(urls,1):
        record=metadata.get(_norm(url)); code="metadata_unavailable" if failed or (not record and _commons_title(url)) else None
        result=_merge({"image_url":url,"source_page":url},record,context,code,"Wikimedia metadata was unavailable." if code else None); result["id"]=f"c{index}"; output.append(result)
    return output
