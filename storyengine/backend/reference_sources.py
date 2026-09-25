"""Bounded public-source metadata collection; no pixels, models, or DB writes."""
from __future__ import annotations

import html.parser
import math
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

def _thumb_width(url: str) -> int | None:
    """Read a Wikimedia thumbnail's advertised width; never treats it as pixels."""
    match = re.search(r"/(\d+)px-[^/]+$", urlparse(str(url or "")).path)
    return int(match.group(1)) if match else None

def _thumb_adequate(url: str, thumb_info: dict | None, original_info: dict) -> bool:
    """Check displayed dimensions without pretending a URL can add pixels."""
    if "/thumb/" not in urlparse(str(url or "")).path:
        return False
    thumb_info = thumb_info or {}
    width = int(thumb_info.get("thumbwidth") or _thumb_width(url) or 0)
    height = int(thumb_info.get("thumbheight") or 0)
    if not height:
        original_width, original_height = int(original_info.get("width") or 0), int(original_info.get("height") or 0)
        height = int(width * original_height / original_width) if original_width else 0
    return width >= 500 and height >= 250

def _original_adequate(info: dict) -> bool:
    return int(info.get("width") or 0) >= 500 and int(info.get("height") or 0) >= 250

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
            pages = {_file(page.get("title")): page for page in (query.get("pages") or {}).values() if page.get("title")}
            # Repair only the API answers that cannot meet the real 500x250
            # pixel gate.  A short, wide source needs more than 500px width.
            affected={}
            for requested in asked:
                resolved=_resolve(requested,changes); page=pages.get(resolved)
                info=((page or {}).get("imageinfo") or [{}])[0]
                thumb=info.get("thumburl") or issued.get(info.get("url")) or ""
                if _original_adequate(info) and not _thumb_adequate(thumb, info, info):
                    affected[resolved] = max(500, math.ceil(250 * int(info["width"]) / int(info["height"])))
            repaired={}
            if affected:
                for width in sorted(set(affected.values())):
                    titles=[title for title, target in affected.items() if target == width]
                    repair=await _wm_get(client,_COMMONS_API,params={"action":"query","titles":"|".join(titles),"redirects":1,"normalized":1,"prop":"imageinfo","iiprop":"url|size","iiurlwidth":width,"format":"json"})
                    repair.raise_for_status()
                    for page in ((repair.json().get("query") or {}).get("pages") or {}).values():
                        info=(page.get("imageinfo") or [{}])[0]
                        if "/thumb/" in urlparse(info.get("thumburl") or "").path:
                            repaired[_file(page.get("title"))]=info
    except Exception as exc:
        raise RuntimeError("metadata_unavailable") from exc
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
            repair_info = repaired.get(_resolve(title,changes))
            thumb = (repair_info or {}).get("thumburl") or info.get("thumburl")
            if not thumb or thumb == info.get("url"):
                thumb = issued.get(info.get("url"))
            thumb_info = repair_info or info
            if _thumb_adequate(thumb, thumb_info, info):
                image=thumb
            elif _original_adequate(info) and info.get("url"):
                # The API's exact original is preferable to a short thumbnail;
                # do not manufacture a higher-resolution URL.
                image=info["url"]
            elif _thumb_adequate(original, None, info):
                image=original
            else:
                continue
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

# The nouns a roster can be "about". Longer/rarer words first so "warship" is not read as "ship".
SUBJECT_WORDS = ('submarine', 'aircraft', 'helicopter', 'tank', 'battleship', 'warship', 'locomotive', 'rocket', 'ship')


def roster_subject(*texts) -> str:
    """The machine noun a documentary is about ("submarine"), read from its title/thesis."""
    for text in texts:
        low = str(text or '').lower()
        for word in SUBJECT_WORDS:
            if re.search(rf'\b{word}s?\b', low):
                return word
    return ''


def _category(machine: str, facts: dict | None) -> str:
    # The subject always rides along in searches: "A-class" alone finds Mercedes cars, "A-class submarine" finds boats.
    role = ' '.join(str((facts or {}).get(k) or '') for k in ('subject', 'role')).lower() + ' ' + machine.lower()
    for word in SUBJECT_WORDS:
        if word in role: return word
    if re.search(r'\b(?:agss|ssn|ssbn|ssgn|ss)-\d',role): return 'submarine'
    if re.search(r'\bbb-\d',role): return 'battleship'
    if any(w in role for w in ('bomber','fighter')): return 'aircraft'
    return ''


def _entity_queries(machine: str, names: list[str], facts: dict | None) -> list[str]:
    category = _category(machine, facts)
    # First alias with a real name/class, not an isolated hull number/range.
    meaningful = [n for n in names if not re.fullmatch(r'[A-Z]+-?\d+(?:\s+through\s+[A-Z]+-?\d+)?',n,re.I)]
    subject = meaningful[0] if meaningful else machine
    subject = re.sub(r'^(?:(?:[A-Z]+-\d+\+?)[,\s]*(?:through\s*)?)+\s*','',subject)
    # A year in the name ("Texas (1892)") is what separates it from its namesakes; keep it.
    year = re.search(r'\((?:[^)]*\D)?((?:18|19|20)\d\d)\b[^)]*\)',subject)
    subject = re.sub(r'\s*\([^)]*\)','',subject).strip()
    subject = re.sub(r'\s+class\b','-class',subject,flags=re.I)
    subject = subject.replace('"','').strip()
    designation = re.search(r'\b(?:[A-Z]{1,6})-\d+\b',machine)
    # A one-ship name alone ("Iowa") finds the state or a later namesake; its hull number pins the ship.
    pin = (f'"{designation.group()}"' if designation and designation.group() not in subject
           and not subject.lower().endswith('-class') else '')
    queries = []
    if subject: queries.append(' '.join(x for x in (f'"{subject}"',pin,category,year.group(1) if year else '') if x))
    if designation: queries.append(' '.join(x for x in (f'"{designation.group()}"',category) if x))
    return list(dict.fromkeys(queries))[:2]


def _wide_queries(machine: str, names: list[str], facts: dict | None) -> list[str]:
    """Second-pass searches for a machine the exact queries found nothing for:
    every name alone, unquoted, with its subject noun ("Ka-22 helicopter")."""
    category = _category(machine, facts)
    queries = []
    for name in names:
        bare = re.sub(r'\s*\([^)]*\)', '', name).replace('"', '').strip()
        if bare:
            queries.append(bare if not category or category in bare.lower() else f'{bare} {category}')
    return list(dict.fromkeys(queries))


def _search_queries(names: list[str], facts: dict | None) -> list[str]:
    return _entity_queries(names[-1] if names else '', names, facts)


async def _resolve_article_titles(machine: str, names: list[str], facts: dict | None) -> list[str]:
    queries = _entity_queries(machine,names,facts)
    groups = []
    async with httpx.AsyncClient(timeout=30,headers=_COMMONS_UA) as client:
        for query in queries:
            try:
                response=await _wm_get(client,_WIKIPEDIA_API,params={'action':'query','list':'search',
                    'srsearch':query,'srnamespace':0,'srlimit':3,'format':'json'})
                response.raise_for_status()
                groups.append([x['title'] for x in (response.json().get('query') or {}).get('search',[])
                    if x.get('title') and 'disambiguation' not in x['title'].lower()])
            except (httpx.HTTPError,ValueError,KeyError):
                groups.append([])
    # Reserve room for both exact-designation and named-class results.
    ordered=[]
    for index in range(3):
        for group in groups:
            if index<len(group) and group[index] not in ordered: ordered.append(group[index])
    if not ordered:
        category=_category(machine,facts)
        for name in names[:3]:
            if re.search(r'\bclass\b',name,re.I) and category:
                ordered.append(re.sub(r'[- ]class\b', '-class '+category,name,flags=re.I))
            elif len(name.split())>1: ordered.append(name)
    return ordered[:4]


async def _article_sources(machine, names, facts):
    from reference_article import article_pack
    return await article_pack(await _resolve_article_titles(machine,names,facts))


def _image_identity(candidate):
    title=_commons_title(candidate.get('image_url') or '')
    if not title and str(candidate.get('title') or '').lower().startswith('file:'):
        title=_file(candidate['title'])
    return title.casefold() if title else _norm(candidate.get('image_url') or '')


async def collect_candidates(machine: str, aliases=None, *, facts=None, manual_url=None, source_page_url=None, cached_url=None,
                             wide=False) -> list[dict]:
    """Gather exact-entity article photos and safe quoted searches automatically.

    ``wide`` is the second pass for a machine the first found no usable photo
    for: the article photos already failed, so only the looser searches run."""
    names=_names(machine,aliases)
    if manual_url and re.search(r'(?:^|[./])(google|bing|duckduckgo)\.|[?&]q=|/search',manual_url,re.I):
        result=_candidate(manual_url,reason_code='search_result_url',reason='Paste a direct image URL, not a search-results page.')
        result['id']='c1';return [result]
    pack=await _article_sources(machine,names,facts)
    context=pack.get('context') or []
    article_images=pack.get('images') or []
    bases=[];by_identity={}
    def add(base):
        if not base.get('image_url'):return
        identity=_image_identity(base)
        if identity in by_identity:
            existing=by_identity[identity]
            for evidence in base.get('evidence',[]):
                if evidence not in existing.setdefault('evidence',[]):existing['evidence'].append(evidence)
            if base.get('caption'):existing['caption']=base['caption']
            return
        if len(bases)>=MAX_CANDIDATES:return
        copied=dict(base);copied['evidence']=list(base.get('evidence') or [])
        bases.append(copied);by_identity[identity]=copied
    if manual_url:
        add(_candidate(manual_url,source_page=source_page_url or manual_url))
        identity=_image_identity(bases[0])
        for item in article_images:
            if _image_identity(item)==identity:add(item)
    elif wide:
        for query in _wide_queries(machine,names,facts):
            if len(bases)>=MAX_CANDIDATES:break
            for row in await find_commons_photos(query,limit=6):
                add(_candidate(row['url'],title=row.get('title','')))
    else:
        if cached_url:add(_candidate(cached_url))
        for item in article_images:add(item)
        for query in _entity_queries(machine,names,facts):
            if len(bases)>=MAX_CANDIDATES:break
            for row in await find_commons_photos(query,limit=4):
                add(_candidate(row['url'],title=row.get('title','')))
    urls=[b['image_url'] for b in bases]
    try:metadata=await _commons_metadata(urls);failed=False
    except RuntimeError:metadata={};failed=True
    output=[]
    for index,base in enumerate(bases,1):
        record=metadata.get(_norm(base['image_url'])) or {}
        evidence=list(record.get('evidence') or [])
        for item in (base.get('evidence') or [])+context:
            if item not in evidence:evidence.append(item)
        code=reason=None
        if manual_url and source_page_url:
            page_evidence,code,reason=await _fetch_source_page(source_page_url,manual_url)
            evidence+=page_evidence
        if (failed or not record) and _commons_title(base['image_url']) and not any(e.get('kind')=='image_caption' for e in evidence):
            code,reason='metadata_unavailable','Image metadata and a linked source caption were unavailable.'
        result=_candidate(record.get('image_url') or base['image_url'],
            source_page=record.get('source_page') or base.get('source_page'),
            title=record.get('title') or base.get('title',''),
            caption=record.get('caption') or base.get('caption',''),
            width=record.get('width'),height=record.get('height'),evidence=evidence,reason_code=code,reason=reason)
        result['id']=f'c{index}';output.append(result)
    return output
