"""Historical cache names are candidates, not an identity bypass."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import static_docu as sd

@pytest.mark.asyncio
@pytest.mark.parametrize('machine,aliases,old', [
    ('D94 HMS Activity', ['HMS Activity', 'D94'], 'HMS Activity (D94) Activity class'),
    ('I72 HMS Unicorn', ['HMS Unicorn', 'I72'], 'HMS Unicorn (I72)'),
    ('Nairana class', ['Nairana', 'Vindex'], 'HMS Vindex'),
])
async def test_reordered_name_requires_fresh_strict_identity(monkeypatch, machine, aliases, old):
    fetch = AsyncMock(return_value=[dict(machine=old, hosted_url='hosted', source_url='source')])
    vision, write, clear = AsyncMock(return_value=True), AsyncMock(), AsyncMock()
    for name, mock in [('fetch_all',fetch),('_vision_confirms',vision),('execute',write),('_clear_reference_miss',clear)]:
        monkeypatch.setattr(sd,name,mock)
    facts = {'role':'WWII escort carrier','years':'1942-1945'}
    assert await sd._recover_cached_roster_reference('tenant-a','video',machine,aliases,facts)
    sql, tenant, patterns = fetch.call_args.args
    assert "tenant_id=$1 AND reference_kind='photo'" in sql and tenant == 'tenant-a'
    assert vision.call_args.kwargs == dict(trusted_source=False, facts=facts, source_label='source')
    assert write.call_args.args[2:4] == (sd._machine_key(machine),machine)
    assert 'DELETE' not in write.call_args.args[0]
    clear.assert_awaited_once_with('tenant-a','video',machine)

@pytest.mark.asyncio
async def test_generic_names_do_not_search_cache(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(sd,'fetch_all',fetch)
    assert not await sd._recover_cached_roster_reference('tenant','video','British aircraft carrier class',[],{})
    fetch.assert_not_awaited()

@pytest.mark.asyncio
async def test_cache_candidates_are_bounded_and_name_filtered(monkeypatch):
    rows = [dict(machine='Different ship',hosted_url='irrelevant',source_url='irrelevant')]
    rows += [dict(machine='HMS Activity',hosted_url=f'hosted{i}',source_url=f'source{i}') for i in range(12)]
    monkeypatch.setattr(sd,'fetch_all',AsyncMock(return_value=rows))
    vision, write = AsyncMock(return_value=False), AsyncMock()
    monkeypatch.setattr(sd,'_vision_confirms',vision)
    monkeypatch.setattr(sd,'execute',write)
    assert not await sd._recover_cached_roster_reference('tenant','video','D94 HMS Activity',[],{})
    assert vision.await_count == 6
    write.assert_not_awaited()

@pytest.mark.asyncio
async def test_article_search_preserves_year_and_removes_display_pennant(monkeypatch):
    lead, articles = AsyncMock(return_value=[]), AsyncMock(return_value=[])
    monkeypatch.setattr(sd,'find_wikipedia_lead_images',lead)
    monkeypatch.setattr(sd,'find_article_images',articles)
    monkeypatch.setattr(sd,'find_commons_photos',AsyncMock(return_value=[]))
    await sd._gather_reference_candidates('I36 HMS Vindictive (1918)', ['HMS Vindictive'], None)
    assert lead.call_args.args[0] == ['HMS Vindictive (1918)', 'HMS Vindictive']
    assert articles.call_args.args[0][0] == 'HMS Vindictive (1918)'

@pytest.mark.asyncio
async def test_missing_vision_credentials_cannot_verify_photo(monkeypatch):
    import vault
    monkeypatch.setattr(vault,'get_secret',AsyncMock(return_value=None))
    monkeypatch.setattr(sd,'_download_image_b64',AsyncMock(return_value=('image/jpeg','eA==')))
    assert not await sd._vision_confirms('tenant','hosted','HMS Activity',trusted_source=True)
