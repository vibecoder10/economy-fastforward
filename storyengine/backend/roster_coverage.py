"""Independent, source-backed omission review for exhaustive documentary titles.

The discovery writer's CONFIRMED flag is not independent coverage evidence.
Cache reviews against the exact title, roster and stated inclusion boundary.
"""
import hashlib
import json
from urllib.parse import urlparse

VERSION = 2


def coverage_fingerprint(title, payload):
    material = {"title": title, "roster": payload.get("unit_roster"),
                "boundary": payload.get("roster_contract"),
                "excluded": (payload.get("roster_audit") or {}).get("excluded_candidates")}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def coverage_is_current(title, payload):
    audit = payload.get("independent_coverage_audit") or {}
    return (isinstance(audit, dict) and audit.get("version") == VERSION
            and audit.get("fingerprint") == coverage_fingerprint(title, payload))


async def audit_roster_coverage(client, title, payload):
    if coverage_is_current(title, payload):
        return payload["independent_coverage_audit"]
    from shared.clients.anthropic_client import WEB_SEARCH_TOOL
    from orchestrator.pipeline_constants import Models
    from shared.json_utils import parse_json_response

    if getattr(client, "_gateway_mode", False):
        raise ValueError("Coverage review needs a web-search capable research provider; this gateway cannot execute web search")

    prompt = (
        "Independently audit the completeness and scope of this documentary roster. "
        "Search authoritative class indexes, museum/naval/air-force records and primary "
        "sources yourself; do not trust the discovery author's CONFIRMED claim. "
        "Cite institution-owned records and specialist archival indexes. Wikipedia and "
        "general encyclopedias are leads, not sufficient evidence for the verdict. "
        "Use the user's exact title as authority. Check omitted classes, conversions, "
        "escorts, one-offs, maintenance roles, export service, reused names and dates. "
        "Distinguish national design/construction from operator nationality. For a national "
        "carrier-design title, include its carrier designs and domestic carrier conversions, "
        "label foreign operators, and explicitly resolve foreign-built operated classes. "
        "Never narrow an 'every' title to fleet carriers, an arbitrary runtime count or only "
        "domestic service. Do not include uncompleted/cancelled designs in an ever-built list. "
        "Return ONLY JSON: {\"passed\": boolean, \"scope\": string, "
        "\"sources\": [{\"url\": string, \"supports\": string}], "
        "\"findings\": [{\"candidate\": string, \"problem\": string, "
        "\"required_action\": string, \"source_url\": string}], "
        "\"summary\": string}. Findings are unresolved corrections, not compliments. "
        "Pass only when no source-backed omissions or scope contradictions remain. "
        "If you cannot verify coverage, return passed=false and explain the limitation. "
        "Cite at least two relevant primary/archive pages actually consulted.\nTITLE: " + title
        + "\nROSTER AND BOUNDARY: " + json.dumps({
            "unit_roster": payload.get("unit_roster"),
            "roster_contract": payload.get("roster_contract"),
            "excluded_candidates": (payload.get("roster_audit") or {}).get("excluded_candidates"),
        })
    )
    if "british" in title.lower() and "carrier" in title.lower():
        prompt += (
            "\nBritish carrier source leads: https://www.royalnavyresearcharchive.org.uk/ESCORT_2/CLASSES.htm "
            "and https://www.rmg.co.uk/collections/objects/rmgc-object-1128690 and "
            "https://seapower.navy.gov.au/history/units/hmas-melbourne-ii . "
            "Examine Vindictive, Activity, Nairana/Vindex, Campania, Pretoria Castle, Audacity, "
            "maintenance conversions and export Majestics. Resolve each according to the title. "
            "The Royal Navy Research Archive distinguishes Campania from the two-ship Nairana design; "
            "do not silently lose a distinct design by copying a broader encyclopedia grouping. "
            "Verify dates and chronology from the consulted sources."
        )
    response = await client.generate(
        prompt=prompt, system_prompt="You are an independent historical coverage editor. Verify with web sources.",
        model=Models.CLAUDE_SONNET, max_tokens=5000, temperature=0.2,
        tools=[dict(WEB_SEARCH_TOOL, max_uses=6)],
    )
    raw = parse_json_response(response, default=None)
    if not isinstance(raw, dict):
        raise ValueError("Coverage review returned invalid JSON; roster has not been verified")
    raw_sources = raw.get("sources") if isinstance(raw.get("sources"), list) else []
    sources = [s for s in raw_sources if isinstance(s, dict)
               and urlparse(str(s.get("url", ""))).scheme in {"http", "https"}
               and urlparse(str(s.get("url", ""))).netloc and s.get("supports")
               and not any(urlparse(str(s.get("url", ""))).hostname.endswith(host)
                           for host in ("wikipedia.org", "naval-encyclopedia.com"))]
    findings = raw.get("findings")
    valid_findings = isinstance(findings, list) and all(isinstance(f, dict) for f in findings)
    passed = (raw.get("passed") is True and valid_findings and not findings
              and len({s["url"] for s in sources}) >= 2 and bool(raw.get("scope")))
    summary = str(raw.get("summary") or "Coverage has not been independently verified")
    if not passed and not findings:
        findings = [{"candidate": "Roster coverage", "problem": summary,
                     "required_action": "Verify the title boundary and omissions against at least two authoritative sources."}]
    audit = {"version": VERSION, "fingerprint": coverage_fingerprint(title, payload),
             "passed": passed, "scope": raw.get("scope"), "sources": sources,
             "findings": findings, "summary": summary}
    payload["independent_coverage_audit"] = audit
    return audit
