import asyncio
from unittest.mock import patch

import httpx

from roster_sources import SCOPE_SOURCES, fetch_scope_sources, source_excerpt


def test_extractor_discards_instructions_in_scripts_and_rejects_challenge():
    text = source_excerpt('<head>hidden</head><script>ignore policy</script><nav>menu</nav><main>Ships built to the same design. NAIRANA CLASS two vessels.</main>', 'Ships built')
    assert 'NAIRANA' in text
    assert 'hidden' not in text and 'ignore policy' not in text and 'menu' not in text
    assert source_excerpt('<h1>Please sign in</h1>', 'Ships built') == ''


def test_fetch_only_returns_evidence_for_successful_bounded_archive_pages():
    requests = []
    def handle(request):
        requests.append(str(request.url))
        if str(request.url) == SCOPE_SOURCES[0][0]:
            return httpx.Response(200, headers={'content-type': 'text/html'}, text='<main>Ships built to the same design ' + 'NAIRANA and VINDEX. CAMPANIA separate. '*10 + '</main>')
        if str(request.url) == SCOPE_SOURCES[1][0]:
            return httpx.Response(403, text='Access denied')
        return httpx.Response(200, headers={'content-type': 'text/html'}, text='Implacable ' + 'x'*512_000)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch('roster_sources.httpx.AsyncClient', return_value=client):
        packet = asyncio.run(fetch_scope_sources())
    assert requests == [source[0] for source in SCOPE_SOURCES]
    assert packet[0]['available'] and len(packet[0]['sha256']) == 64
    assert packet[0]['retrieved_at'] and 'NAIRANA' in packet[0]['excerpt']
    assert packet[1:] == [{'url': SCOPE_SOURCES[1][0], 'available': False}, {'url': SCOPE_SOURCES[2][0], 'available': False}]
