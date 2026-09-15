from unittest.mock import AsyncMock
import pytest
import static_docu as sd
import vault

@pytest.mark.asyncio
@pytest.mark.parametrize('reply, expected', [('[2,1]', ['upper.jpg','side.jpg','underside.jpg']), ('[2,2]', ['side.jpg','upper.jpg','underside.jpg'])])
async def test_visual_rank_keeps_candidates_and_falls_back_on_invalid_order(monkeypatch,reply,expected):
    monkeypatch.setattr(vault,'get_secret',AsyncMock(return_value='test-key'))
    monkeypatch.setattr(sd,'_download_image_b64',AsyncMock(side_effect=[('image/jpeg','eA=='),('image/jpeg','eA=='),None]))
    captured=[]
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'content':[{'type':'text','text':reply}]}
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,**kwargs): captured.append(kwargs['json']);return Response()
    monkeypatch.setattr(sd.httpx,'AsyncClient',lambda **kwargs:Client())
    candidates=[('underside.jpg',True),('side.jpg',True),('upper.jpg',True)]
    result=await sd._rank_reference_views(candidates,'tenant','B-1A')
    assert [c[0] for c in result]==expected
    prompt=captured[0]['messages'][0]['content'][0]['text']
    assert 'ENTIRE machine' in prompt and 'UPPER surfaces' in prompt
    assert 'different variant is not a better reference' in prompt

@pytest.mark.asyncio
async def test_rank_without_key_does_not_block_or_lose_candidates(monkeypatch):
    monkeypatch.setattr(vault,'get_secret',AsyncMock(return_value=None))
    assert await sd._rank_reference_views([('underside.jpg',True),('upper.jpg',True)],'tenant','B-1A') == [('upper.jpg',True),('underside.jpg',True)]
