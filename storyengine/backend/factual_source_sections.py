"""Keep exact named-vessel evidence within the publisher's HTML sections."""
from __future__ import annotations

import html
import re


def html_visible_sections(raw_html: str) -> str:
    text = re.sub(r'(?is)<(script|style|noscript|svg|header|footer|nav)\b[^>]*>.*?</\1>', ' ', raw_html or '')
    sections = []
    for section in re.split(r'(?is)(?=<h[1-6](?:\s|>))', text):
        visible = ' '.join(html.unescape(re.sub(r'(?is)<[^>]+>', ' ', section)).split())
        if visible:
            sections.append(visible)
    return '\n\n'.join(sections)


def has_foreign_ship(text: str, machine: str) -> bool:
    from factual_machine_research import named_submarine_target, _NAMED_SUBMARINE_HULL_RE
    target = named_submarine_target(machine)
    if not target:
        return False
    prefixes = {'SS', 'AGSS'} if target['prefix'] in {'SS', 'AGSS'} else {target['prefix']}
    for hull in _NAMED_SUBMARINE_HULL_RE.finditer(text):
        if hull.group('prefix').upper() not in prefixes or hull.group('number') != target['number']:
            return True
    if re.search(r'\b(?:HMS|HMAS|HNLMS|IJN)\s', text, re.I):
        return True
    name = r'[\s._,\-–—]+'.join(re.escape(w) for w in re.findall(r'[A-Za-z0-9]+', target['name']))
    for prefix in re.finditer(r'\bUSS\s+', text, re.I):
        if not re.match(name + r'(?![A-Za-z0-9])', text[prefix.end():], re.I):
            # A publisher's explicit rename statement belongs to the anchored
            # subject. This exception applies only to that occurrence, never
            # to subsequent passages using the alias or another hull number.
            if re.search(r'\brenamed\s+$', text[:prefix.start()], re.I):
                continue
            return True
    return False


def anchored_section_prefix(section: str, machine: str, matcher, max_chars: int = 3000) -> str:
    """Retain original adjacent text, ending before a competing ship identity.

    An anchored heading may govern later specs or pronouns. Never jump over a
    competing identity, and never manufacture an identity prefix for a quote.
    """
    section = ' '.join(section.split())
    sentences = list(re.finditer(r'.+?(?:[.!?](?=\s)|$)', section))
    start = None
    end = None
    count = 0
    for sentence in sentences:
        text = sentence.group().strip()
        if start is None:
            if not matcher(text, machine) or has_foreign_ship(text, machine):
                continue
            start = sentence.start()
            while start < sentence.end() and section[start].isspace():
                start += 1
        if has_foreign_ship(text, machine) or sentence.end() - start > max_chars:
            break
        end = sentence.end()
        count += 1
    return section[start:end] if start is not None and end is not None and count > 1 else ''


def verified_archive_url(snapshot, original_url: str) -> str:
    """Accept only the availability API's real snapshot for this same source."""
    from urllib.parse import urlsplit, urlunsplit
    if not isinstance(snapshot, dict) or snapshot.get('available') is not True or str(snapshot.get('status')) != '200':
        return ''
    value = snapshot.get('url')
    if not isinstance(value, str):
        return ''
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return ''
    if parsed.hostname != 'web.archive.org' or parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or port not in {None, 80, 443}:
        return ''
    match = re.fullmatch(r'/web/\d{14}(?:id_|if_)?/(https?://.+)', parsed.path + ('?' + parsed.query if parsed.query else ''))
    if not match:
        return ''
    captured, requested = urlsplit(match.group(1)), urlsplit(original_url)
    if (captured.netloc.lower(), captured.path, captured.query) != (requested.netloc.lower(), requested.path, requested.query):
        return ''
    return urlunsplit(('https', 'web.archive.org', parsed.path, parsed.query, ''))
