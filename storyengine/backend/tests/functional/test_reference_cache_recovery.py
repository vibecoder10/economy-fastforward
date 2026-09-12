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
async def test_duplicate_rejections_fall_through_to_web(monkeypatch):
    row = dict(machine='HMS Activity (D94)',hosted_url='old',source_url='same')
    monkeypatch.setattr(sd,'fetch_all',AsyncMock(return_value=[row,row]))
    vision = AsyncMock(side_effect=[False,True])
    monkeypatch.setattr(sd,'_vision_confirms',vision)
    gather = AsyncMock(return_value=[('fresh',False)])
    monkeypatch.setattr(sd,'_gather_reference_candidates',gather)
    monkeypatch.setattr(sd,'_host_reference',AsyncMock(return_value='fresh-hosted'))
    write = AsyncMock()
    monkeypatch.setattr(sd,'execute',write)
    monkeypatch.setattr(sd,'_clear_reference_miss',AsyncMock())
    assert await sd._prefetch_one_machine('tenant','video','D94 HMS Activity',0)
    assert vision.await_count == 2
    gather.assert_awaited_once()
    assert write.await_count == 1 and write.call_args.args[-2:] == ('fresh-hosted','fresh')

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
async def test_missing_year_uses_current_roster_dates_only_as_search_hints(monkeypatch):
    monkeypatch.setattr(sd,'_recover_cached_roster_reference',AsyncMock(return_value=False))
    gather = AsyncMock(return_value=[])
    monkeypatch.setattr(sd,'_gather_reference_candidates',gather)
    monkeypatch.setattr(sd,'find_commons_photos',AsyncMock(return_value=[]))
    monkeypatch.setattr(sd,'_record_reference_miss',AsyncMock())
    await sd._prefetch_one_machine('tenant','video','I36 HMS Vindictive',0,['HMS Vindictive'],
        {'years':'Laid down 1916, commissioned 1918, converted 1925 [Source 2024]'})
    assert gather.call_args.args[1] == ['HMS Vindictive','HMS Vindictive (1916)','HMS Vindictive (1918)']

@pytest.mark.asyncio
async def test_missing_vision_credentials_cannot_verify_photo(monkeypatch):
    import vault
    monkeypatch.setattr(vault,'get_secret',AsyncMock(return_value=None))
    monkeypatch.setattr(sd,'_download_image_b64',AsyncMock(return_value=('image/jpeg','eA==')))
    assert not await sd._vision_confirms('tenant','hosted','HMS Activity',trusted_source=True)
