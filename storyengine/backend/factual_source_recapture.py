"""Free original-source capture for known citations; never calls discovery or a model."""
from __future__ import annotations


def validated_source_urls(urls):
    from factual_source_search import public_source_url
    if not isinstance(urls, list) or len(urls) > 6:
        raise ValueError('Supply at most six original source URLs.')
    result = []
    for raw in urls:
        url = public_source_url(raw)
        if not url:
            raise ValueError('Source URL must be a public HTTP(S) URL.')
        if url not in result:
            result.append(url)
    return result


async def recapture_sources(ex, title, machine, urls):
    import httpx
    from factual_source_search import guard_public_request
    from factual_machine_research import candidate_mentions_machine
    from contextual_source_identity import contextual_named_excerpt
    from pipeline_executor import _sentence_candidates_from_source, _source_text_fingerprint, _source_tier_for_url
    urls = validated_source_urls(urls)
    package = {'machine': machine, 'sources': [], 'candidate_excerpts': [], 'search_queries': [], 'errors': []}
    def matches(text, target):
        return candidate_mentions_machine(text, target) or contextual_named_excerpt(text, target)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, event_hooks={'request': [guard_public_request]}) as client:
        for url in urls:
            text = await ex._fetch_source_text(client, url)
            excerpts = _sentence_candidates_from_source(text, machine, limit=10, matcher=matches)
            if not excerpts:
                package['errors'].append({'url': url, 'reason': 'No usable named-machine excerpt in source capture.'})
                continue
            sid = f'R{len(package["sources"])+1}'
            tier = _source_tier_for_url(url, url)
            package['sources'].append({'source_id': sid, 'title': url, 'url': url,
                'source_capture_method': 'fetched_page', 'source_tier': tier['tier'],
                'text_hash': _source_text_fingerprint(text), 'text_chars': len(text)})
            for index, excerpt in enumerate(excerpts, 1):
                eid = f'{sid}-E{index}'
                package['candidate_excerpts'].append({'excerpt_id': eid, 'source_id': sid,
                    'source_title': url, 'source_url': url, 'source_tier': tier['tier'],
                    'source_capture_method': 'fetched_page', 'locator': f'{eid}; source={url}',
                    'text': excerpt, 'text_hash': _source_text_fingerprint(excerpt)})
    return package
