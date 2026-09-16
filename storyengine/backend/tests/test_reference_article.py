import pytest

import reference_article as article
import reference_sources as sources


class Response:
    def __init__(self, body): self.body = body
    def raise_for_status(self): return None
    def json(self): return self.body


@pytest.mark.asyncio
async def test_article_pack_binds_figure_caption_to_its_image(monkeypatch):
    async def wm(_client, _url, *, params):
        assert params["action"] == "parse" and params["prop"] == "text|wikitext"
        return Response({"parse": {"title": "Example vessel", "text": {"*": """
          <p>Visible article fact.</p><figure><a href='/wiki/File:Vessel.jpg'><img src='//upload.wikimedia.org/a.jpg'></a><figcaption>USS Example underway</figcaption></figure>
        """}}})
    monkeypatch.setattr(article, "_wm_get", wm)
    pack = await article.article_pack(["Example vessel"])
    assert pack["images"][0]["title"] == "File:Vessel.jpg"
    assert pack["images"][0]["caption"] == "USS Example underway"
    assert pack["images"][0]["image_url"] == "https://upload.wikimedia.org/a.jpg"
    assert pack["images"][0]["evidence"][1]["text"] == "Visible article fact. USS Example underway"


@pytest.mark.asyncio
async def test_article_pack_supports_legacy_thumb_and_infobox_caption(monkeypatch):
    async def wm(_client, _url, *, params):
        return Response({"parse": {"title": "Example", "text": {"*": """
          <div class='thumb'><a href='/wiki/File:Legacy.jpg'><img src='/legacy.jpg'></a><div class='thumbcaption'>Legacy caption</div></div>
          <table class='infobox'><tr><td class='infobox-image'><a href='/wiki/File:Box.jpg'><img src='/box.jpg'></a></td></tr><tr class='infobox-caption'><td>Infobox caption</td></tr></table>
        """}}})
    monkeypatch.setattr(article, "_wm_get", wm)
    pack = await article.article_pack(["Example"])
    assert [(row["title"], row["caption"]) for row in pack["images"]] == [
        ("File:Legacy.jpg", "Legacy caption"), ("File:Box.jpg", "Infobox caption")]


@pytest.mark.asyncio
async def test_article_pack_never_claims_unrelated_or_missing_caption(monkeypatch):
    async def wm(_client, _url, *, params):
        return Response({"parse": {"text": {"*": """
          <p>Article heading is not an image caption.</p><img src='/plain.jpg'>
          <figure><a href='/wiki/File:One.jpg'><img src='/one.jpg'></a><figcaption>One only</figcaption></figure>
          <img src='/two.jpg'><p>Unrelated paragraph.</p>
        """}}})
    monkeypatch.setattr(article, "_wm_get", wm)
    pack = await article.article_pack(["Example"])
    assert [(row["title"], row["caption"]) for row in pack["images"]] == [("File:One.jpg", "One only")]


@pytest.mark.asyncio
async def test_original_550_uses_api_500_thumb_instead_of_cached_330(monkeypatch):
    raw = "https://upload.wikimedia.org/wikipedia/commons/a/a/Sample.jpg"
    cached = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a/Sample.jpg/330px-Sample.jpg"
    calls = []
    async def wm(_client, _url, *, params):
        calls.append(params)
        if params["iiurlwidth"] == 1536:
            return Response({"query": {"pages": {"1": {"title": "File:Sample.jpg", "imageinfo": [{
                "url": raw, "thumburl": cached, "width": 550, "height": 440, "descriptionurl": "https://commons.wikimedia.org/wiki/File:Sample.jpg"}]}}}})
        assert params["iiurlwidth"] == 500
        return Response({"query": {"pages": {"1": {"title": "File:Sample.jpg", "imageinfo": [{"thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a/Sample.jpg/500px-Sample.jpg"}]}}}})
    monkeypatch.setattr(sources, "_wm_get", wm)
    rows = await sources._commons_metadata([raw])
    assert rows[sources._norm(raw)]["image_url"].endswith("/500px-Sample.jpg")
    assert [call["iiurlwidth"] for call in calls] == [1536, 500]


@pytest.mark.asyncio
async def test_short_wide_original_keeps_api_original_when_690_thumb_is_too_short(monkeypatch):
    raw = "https://upload.wikimedia.org/wikipedia/commons/a/a/Barracuda.jpg"
    cached = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a/Barracuda.jpg/330px-Barracuda.jpg"
    calls = []
    async def wm(_client, _url, *, params):
        calls.append(params)
        if params["iiurlwidth"] == 1536:
            return Response({"query": {"pages": {"1": {"title": "File:Barracuda.jpg", "imageinfo": [{
                "url": raw, "thumburl": cached, "width": 750, "height": 272}]}}}})
        assert params["iiurlwidth"] == 690
        return Response({"query": {"pages": {"1": {"title": "File:Barracuda.jpg", "imageinfo": [{
            "thumburl": "https://upload.wikimedia.org/wikipedia/commons/a/a/Barracuda.jpg?thumbnail_unscaled=1",
            "thumbwidth": 690, "thumbheight": 250}]}}}})
    monkeypatch.setattr(sources, "_wm_get", wm)
    rows = await sources._commons_metadata([raw])
    assert rows[sources._norm(raw)]["image_url"] == raw
    assert [call["iiurlwidth"] for call in calls] == [1536, 690]
