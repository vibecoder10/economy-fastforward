import pytest

import reference_sources as rs
from unittest.mock import AsyncMock


def test_roster_role_disambiguates_discovery_without_inventing_identity():
    assert rs._search_queries(['Albacore class','AGSS-569','ignored'],{'role':'Experimental research submarine'}) == ['"Albacore-class" submarine']
    assert rs._search_queries(['Boeing XB-15'],{'role':'Heavy bomber'}) == ['"Boeing XB-15" aircraft','"XB-15" aircraft']
    assert rs._search_queries(['"Unknown-class"'],{}) == ['"Unknown-class"']


@pytest.fixture(autouse=True)
def no_live_commons_search(monkeypatch):
    monkeypatch.setattr(rs, "find_commons_photos", AsyncMock(return_value=[]))
    monkeypatch.setattr(rs, "_article_sources", AsyncMock(return_value={"context":[],"images":[]}))


class Response:
    def __init__(self, body): self.body = body
    def raise_for_status(self): return None
    def json(self): return self.body


@pytest.mark.asyncio
async def test_commons_metadata_maps_raw_thumb_normalized_redirect_and_html(monkeypatch):
    raw = "https://upload.wikimedia.org/wikipedia/commons/a/a1/Foo_bar.jpg"
    thumb = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/Foo_bar.jpg/1280px-Foo_bar.jpg"
    async def wm(_client, _url, *, params):
        assert params["iiprop"] == "url|size|extmetadata" and params["iiurlwidth"] == 1536
        return Response({"query": {"normalized": [{"from":"File:Foo_bar.jpg","to":"File:Foo bar.jpg"}],
          "redirects": [{"from":"File:Foo bar.jpg","to":"File:Target.jpg"}],
          "pages": {"1": {"title":"File:Target.jpg", "imageinfo":[{"thumburl":"https://upload.wikimedia.org/wikipedia/commons/thumb/z/1/Target.jpg/1536px-Target.jpg","width":2000,"height":1000,"descriptionurl":"https://commons.wikimedia.org/wiki/File:Target.jpg","extmetadata":{"ImageDescription":{"value":"<b>USS</b> Target"},"Source":{"value":"<a>Archive</a>"},"Credit":{"value":"<i>Photographer</i>"},"DateTimeOriginal":{"value":"1960"}}}]}}}})
    async def issued(_client, urls):
        assert urls == [raw]
        return {raw:"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/Foo_bar.jpg/1536px-Foo_bar.jpg"}
    monkeypatch.setattr(rs, "_wm_get", wm); monkeypatch.setattr(rs, "_api_issued_thumbs_batch", issued)
    records = await rs._commons_metadata([raw, thumb])
    assert records[rs._norm(raw)]["image_url"].endswith("1536px-Target.jpg")
    assert records[rs._norm(thumb)]["image_url"].endswith("1536px-Target.jpg")
    record = records[rs._norm(raw)]
    assert record["caption"] == "USS Target" and record["source_page"].endswith("File:Target.jpg")
    assert "Source: Archive" in record["evidence"][1]["text"] and "Credit: Photographer" in record["evidence"][1]["text"]


@pytest.mark.asyncio
async def test_manual_commons_succeeds_without_optional_source_page(monkeypatch):
    thumb="https://upload.wikimedia.org/wikipedia/commons/thumb/a/a/Foo.jpg/800px-Foo.jpg"
    async def wm(_client, _url, *, params):
        return Response({"query":{"pages":{"1":{"title":"File:Foo.jpg","imageinfo":[{"width":800,"height":500,"descriptionurl":"https://commons.wikimedia.org/wiki/File:Foo.jpg","extmetadata":{"ImageDescription":{"value":"<b>Named</b> boat"}}}]}}}})
    async def context(_): return []
    monkeypatch.setattr(rs,"_wm_get",wm); monkeypatch.setattr(rs,"_wiki_context",context)
    rows=await rs.collect_candidates("Example",manual_url=thumb)
    assert len(rows)==1 and rows[0]["id"]=="c1" and rows[0]["caption"]=="Named boat"
    assert rows[0]["image_url"] == thumb and "reason_code" not in rows[0]


@pytest.mark.asyncio
async def test_manual_google_rejected_before_fetch(monkeypatch):
    async def bad(*_a, **_k): raise AssertionError("must not fetch")
    monkeypatch.setattr(rs,"_fetch_source_page",bad)
    monkeypatch.setattr(rs,"_wiki_context",bad)
    rows=await rs.collect_candidates("X",manual_url="https://www.google.com/search?q=x")
    assert rows[0]["id"]=="c1" and rows[0]["reason_code"]=="search_result_url"
    assert "direct image URL" in rows[0]["reason"]


@pytest.mark.asyncio
async def test_manual_source_page_requires_exact_query_link(monkeypatch):
    class Page:
        content=b'<a href="https://img.example/a.jpg?size=small">image</a>'
        def raise_for_status(self): return None
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*_): return None
        async def get(self,_): return Page()
    monkeypatch.setattr(rs.httpx,"AsyncClient",lambda **_: Client())
    evidence,code,_=await rs._fetch_source_page("https://archive.example/page","https://img.example/a.jpg?size=large")
    assert not evidence and code=="source_link_missing"


@pytest.mark.asyncio
async def test_automatic_cached_first_even_when_discovery_has_twelve(monkeypatch):
    cached="https://cached.example/a.jpg"
    async def gather(*_): return [(f"https://x.example/{i}.jpg",False) for i in range(12)]
    async def commons(*_,**__): raise AssertionError("capacity already full")
    async def metadata(urls): return {}
    async def context(_): return []
    monkeypatch.setattr(rs,"_article_sources",AsyncMock(return_value={"context":[],"images":[{"image_url":f"https://x.example/{i}.jpg"} for i in range(12)]})); monkeypatch.setattr(rs,"find_commons_photos",commons)
    monkeypatch.setattr(rs,"_commons_metadata",metadata); monkeypatch.setattr(rs,"_wiki_context",context)
    rows=await rs.collect_candidates("Machine",["Alias"],cached_url=cached)
    assert len(rows)==12 and rows[0]["image_url"]==cached


@pytest.mark.asyncio
async def test_automatic_dedupes_file_identity_and_caps_actual_photos(monkeypatch):
    photo={"image_url":"https://x.example/dupe.jpg"}
    monkeypatch.setattr(rs,"_article_sources",AsyncMock(return_value={"context":[],"images":[photo]*20}))
    calls=[]
    async def commons(query,limit=4):
        calls.append(query)
        return [{"url":f"https://x.example/{len(calls)}-{i}.jpg"} for i in range(4)]
    monkeypatch.setattr(rs,"find_commons_photos",commons)
    monkeypatch.setattr(rs,"_commons_metadata",AsyncMock(return_value={}))
    rows=await rs.collect_candidates('SS-100 through SS-103 Example class',['Example class'],facts={'role':'submarine'})
    assert len(rows)==9 and calls==['"Example-class" submarine','"SS-100" submarine']


@pytest.mark.asyncio
async def test_metadata_api_error_is_typed_per_wikimedia_row(monkeypatch):
    url="https://upload.wikimedia.org/wikipedia/commons/thumb/a/a/Foo.jpg/800px-Foo.jpg"
    async def gather(*_): return [(url,False)]
    async def broken(*_): raise RuntimeError("metadata_unavailable")
    async def context(_): return []
    monkeypatch.setattr(rs,"_article_sources",AsyncMock(return_value={"context":[],"images":[{"image_url":url}]})); monkeypatch.setattr(rs,"_commons_metadata",broken); monkeypatch.setattr(rs,"_wiki_context",context)
    rows=await rs.collect_candidates("Machine")
    assert rows[0]["reason_code"]=="metadata_unavailable"


@pytest.mark.asyncio
async def test_manual_excludes_cached(monkeypatch):
    async def context(_): return []
    monkeypatch.setattr(rs,"_wiki_context",context)
    rows=await rs.collect_candidates("X",manual_url="https://img.example/x.jpg",cached_url="https://cached.example.jpg")
    assert len(rows)==1 and rows[0]["image_url"]=="https://img.example/x.jpg"


def test_discovery_never_sends_bare_hull_range_as_search_operators():
    for machine,alias,role in [
        ('SS-105 through SS-162 S-class','S-class','Fleet submarine'),
        ('SS-163 through SS-165 Barracuda (V-1) class','Barracuda (V-1) class','submarine'),
        ('SS-563 through SS-568 Tang class','Tang class','submarine'),
    ]:
        queries=rs._entity_queries(machine,[alias,machine],{'role':role})
        assert len(queries)==2 and all(q.startswith('"') and q.endswith('submarine') for q in queries)
        assert all('through' not in q for q in queries)
    assert rs._entity_queries('SS-105 through SS-162 S-class',['S-class'],{'role':'submarine'})[0]=='"S-class" submarine'


@pytest.mark.asyncio
async def test_article_caption_is_merged_only_with_matching_cached_file(monkeypatch):
    cached='https://upload.wikimedia.org/wikipedia/commons/thumb/a/b/USS_Gudgeon.jpg/960px-USS_Gudgeon.jpg'
    caption={'kind':'image_caption','url':'https://en.wikipedia.org/wiki/Tang-class_submarine','text':'USS Gudgeon (SS-567), a Tang-class submarine.'}
    other={'kind':'image_caption','url':'https://en.wikipedia.org/wiki/Other','text':'Different vessel that must not identify Gudgeon.'}
    pack={'context':[], 'images':[
        {'image_url':cached,'title':'File:USS Gudgeon.jpg','caption':caption['text'],'evidence':[caption]},
        {'image_url':'https://example/other.jpg','title':'File:Other.jpg','evidence':[other]}]}
    monkeypatch.setattr(rs,'_article_sources',AsyncMock(return_value=pack))
    monkeypatch.setattr(rs,'_commons_metadata',AsyncMock(return_value={rs._norm(cached):{'image_url':cached,'caption':'','title':'File:USS Gudgeon.jpg','evidence':[]}}))
    rows=await rs.collect_candidates('Tang class',cached_url=cached)
    assert len(rows)==2 and rows[0]['evidence']==[caption]
    assert 'reason_code' not in rows[0] and rows[0]['caption']==caption['text']
