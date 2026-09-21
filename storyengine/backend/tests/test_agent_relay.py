"""Agent LLM relay: the request store, the blocking AgentRelayClient, and a real DVSU
stage waiting on / resuming from a fake answerer.

The DB is an in-memory fake of exactly the statements agent_relay issues (same pattern as
tests/test_dvsu_script_operations.py); the model is a background task standing in for the
MCP agent. Nothing here calls a provider.
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path

import pytest

_PIPELINE = Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))

import agent_relay as relay  # noqa: E402
import agent_relay_client as relay_client  # noqa: E402
import dvsu_research_v2 as v2  # noqa: E402

TENANT = str(uuid.uuid4())
OTHER_TENANT = str(uuid.uuid4())
VIDEO = str(uuid.uuid4())
OTHER_VIDEO = str(uuid.uuid4())


class FakeDB:
    """Just enough SQL semantics for agent_relay: unique (tenant, scope, fingerprint),
    tenant-filtered reads, UPDATE ... RETURNING."""

    def __init__(self):
        self.rows = {}   # id -> row
        self.relay_flags = {}

    def _by_key(self, tenant, scope, fp):
        return next((r for r in self.rows.values()
                     if (r["tenant_id"], r["scope"], r["fingerprint"]) == (tenant, scope, fp)), None)

    async def execute(self, sql, *args):
        assert sql.lstrip().startswith("INSERT INTO agent_llm_requests")
        tenant, video, scope, fp, stage, model, system, prompt, tools, max_tokens, temp = args
        if self._by_key(tenant, scope, fp):
            return "INSERT 0 0"
        rid = str(uuid.uuid4())
        self.rows[rid] = {
            "id": rid, "tenant_id": tenant, "video_id": video, "scope": scope, "fingerprint": fp,
            "stage": stage, "status": "pending", "model": model, "system_prompt": system,
            "prompt": prompt, "tools": tools, "max_tokens": max_tokens, "temperature": temp,
            "response_text": None, "answer_count": 0, "answered_at": None, "created_at": None,
        }
        return "INSERT 0 1"

    async def fetch_one(self, sql, *args):
        if "FROM tenants" in sql:
            return {"agent_llm_relay": self.relay_flags.get(args[0], False)}
        if sql.lstrip().startswith("UPDATE agent_llm_requests"):
            tenant, rid, response = args
            row = self.rows.get(rid)
            if not row or row["tenant_id"] != tenant:
                return None
            row.update(status="answered", response_text=response, answer_count=row["answer_count"] + 1)
            return dict(row)
        if "count(*)" in sql:
            tenant, *rest = args
            rows = [r for r in self.rows.values() if r["tenant_id"] == tenant and r["status"] == "pending"]
            if rest:
                rows = [r for r in rows if r["video_id"] == rest[0]]
            return {"n": len(rows)}
        if "scope = $2 AND fingerprint = $3" in sql:
            row = self._by_key(*args)
            return dict(row) if row else None
        if "id = $2" in sql:
            tenant, rid = args
            row = self.rows.get(rid)
            return dict(row) if row and row["tenant_id"] == tenant else None
        raise AssertionError(sql)

    async def fetch_all(self, sql, *args):
        tenant, *rest = args
        assert "tenant_id = $1" in sql
        rows = [r for r in self.rows.values() if r["tenant_id"] == tenant]
        if "status = $2" in sql:
            rows = [r for r in rows if r["status"] == rest[0]]
        if "video_id = $" in sql:
            rows = [r for r in rows if r["video_id"] == rest[-2]]
        return [dict(r, age_seconds=1.0) for r in rows]


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(relay, "execute", fake.execute)
    monkeypatch.setattr(relay, "fetch_one", fake.fetch_one)
    monkeypatch.setattr(relay, "fetch_all", fake.fetch_all)
    return fake


def _client(video=VIDEO, tenant=TENANT, **kw):
    return relay_client.AgentRelayClient(tenant, video, poll_seconds=0.01, timeout_seconds=kw.pop("timeout_seconds", 5), **kw)


async def _answer_when_pending(db, respond, tenant=TENANT, count=1):
    """Stand-in for the MCP agent: answers pending requests as they appear."""
    answered = 0
    while answered < count:
        for row in await relay.list_requests(tenant, status="pending"):
            await relay.answer_request(tenant, row["id"], respond(row))
            answered += 1
        await asyncio.sleep(0.005)


# ---- store -------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_request_is_one_row_and_scoped_by_tenant_and_video(db):
    kw = dict(fingerprint="a" * 64, stage="s", model="m", system_prompt="", prompt="p",
              tools=None, max_tokens=10, temperature=0.3)
    first = await relay.get_or_create_request(TENANT, VIDEO, **kw)
    again = await relay.get_or_create_request(TENANT, VIDEO, **kw)
    other_video = await relay.get_or_create_request(TENANT, OTHER_VIDEO, **kw)
    other_tenant = await relay.get_or_create_request(OTHER_TENANT, VIDEO, **kw)
    assert first["id"] == again["id"]
    assert len({first["id"], other_video["id"], other_tenant["id"]}) == 3
    assert first["status"] == "pending"


@pytest.mark.asyncio
async def test_answer_is_tenant_scoped_and_validated(db):
    row = await relay.get_or_create_request(TENANT, VIDEO, fingerprint="b" * 64, stage=None, model="m",
                                            system_prompt="", prompt="p", tools=None, max_tokens=1, temperature=0)
    with pytest.raises(relay.AnswerError, match="No LLM request"):
        await relay.answer_request(OTHER_TENANT, row["id"], "stolen")
    assert db.rows[row["id"]]["status"] == "pending"
    for bad in ("", "   ", None, 5):
        with pytest.raises(relay.AnswerError):
            await relay.answer_request(TENANT, row["id"], bad)
    with pytest.raises(relay.AnswerError, match="limit"):
        await relay.answer_request(TENANT, row["id"], "x" * (relay.MAX_RESPONSE_CHARS + 1))
    with pytest.raises(relay.AnswerError, match="not a request id"):
        await relay.answer_request(TENANT, "not-a-uuid", "x")


@pytest.mark.asyncio
async def test_reanswering_replaces_and_says_so(db):
    row = await relay.get_or_create_request(TENANT, VIDEO, fingerprint="c" * 64, stage=None, model="m",
                                            system_prompt="", prompt="p", tools=None, max_tokens=1, temperature=0)
    first = await relay.answer_request(TENANT, row["id"], "one")
    second = await relay.answer_request(TENANT, row["id"], "two")
    assert first["replaced_previous_answer"] is False and second["replaced_previous_answer"] is True
    assert db.rows[row["id"]]["response_text"] == "two"


@pytest.mark.asyncio
async def test_relay_enabled_reads_tenant_flag_and_fails_closed(db, monkeypatch):
    assert await relay.relay_enabled(TENANT) is False
    db.relay_flags[TENANT] = True
    assert await relay.relay_enabled(TENANT) is True
    assert await relay.relay_enabled(OTHER_TENANT) is False

    async def boom(*a, **k):
        raise RuntimeError("column does not exist")
    monkeypatch.setattr(relay, "fetch_one", boom)
    assert await relay.relay_enabled(TENANT) is False


# ---- client ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_blocks_until_answered_then_returns_exact_text(db):
    client = _client()
    answerer = asyncio.create_task(_answer_when_pending(db, lambda row: '{"ok": true}'))
    text = await client.generate(prompt="question", system_prompt="sys", max_tokens=50, temperature=0.3,
                                 tools=[{"type": "web_search_20250305", "name": "web_search"}])
    await answerer
    assert text == '{"ok": true}'
    (row,) = db.rows.values()
    assert row["stage"] == "test_generate_blocks_until_answered_then_returns_exact_text"
    assert row["prompt"] == "question" and row["system_prompt"] == "sys" and row["status"] == "answered"


@pytest.mark.asyncio
async def test_replay_never_asks_twice_and_is_immediate(db):
    client = _client()
    answerer = asyncio.create_task(_answer_when_pending(db, lambda row: "first answer"))
    assert await client.generate(prompt="q") == "first answer"
    await answerer
    # A fresh client (a restart / a re-run of the stage) replays with zero waiting: a 30s
    # poll interval would blow the 1s deadline if replay ever went through the wait loop.
    replay = relay_client.AgentRelayClient(TENANT, VIDEO, poll_seconds=30, timeout_seconds=60)
    assert await asyncio.wait_for(replay.generate(prompt="q"), 1) == "first answer"
    assert len(db.rows) == 1


@pytest.mark.asyncio
async def test_different_inputs_are_different_requests(db):
    client = _client()
    answerer = asyncio.create_task(_answer_when_pending(db, lambda row: row["prompt"].upper(), count=3))
    assert await client.generate(prompt="a") == "A"
    assert await client.generate(prompt="a", temperature=0.2) == "A"
    assert await client.generate(prompt="b") == "B"
    await answerer
    assert len(db.rows) == 3


@pytest.mark.asyncio
async def test_timeout_leaves_the_request_pending_and_a_later_run_resumes(db):
    with pytest.raises(relay_client.AgentRelayTimeout, match="still pending"):
        await _client(timeout_seconds=0.05).generate(prompt="slow")
    (row,) = db.rows.values()
    assert row["status"] == "pending"
    await relay.answer_request(TENANT, row["id"], "late answer")
    assert await _client(timeout_seconds=0.05).generate(prompt="slow") == "late answer"
    assert len(db.rows) == 1


@pytest.mark.asyncio
async def test_cancel_while_waiting_raises(db):
    async def cancelled():
        return True
    with pytest.raises(relay_client.AgentRelayCancelled):
        await _client(should_cancel=cancelled).generate(prompt="q")
    assert list(db.rows.values())[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_bind_scopes_later_calls_to_the_video(db):
    client = _client(video=None)
    client.bind(VIDEO)
    answerer = asyncio.create_task(_answer_when_pending(db, lambda row: "x"))
    await client.generate(prompt="q")
    await answerer
    assert list(db.rows.values())[0]["video_id"] == VIDEO


def test_client_looks_like_a_direct_client_to_stage_code():
    client = _client()
    assert client._gateway_mode is False  # DVSU refuses gateway clients
    assert client.api_key is None and client.client is None  # nothing that could spend


# ---- a real stage against a fake answerer -----------------------------------------------

def _slot_answer(prompt):
    return json.dumps({"answer": f"answer for: {prompt[-30:]}", "source_url": "https://example.gov/x", "quote": "q"})


@pytest.mark.asyncio
async def test_dvsu_call3_runs_unchanged_through_the_relay_and_replays_for_free(db):
    def respond(row):
        if "candidates" in row["prompt"] or "outcome" in row["prompt"].lower():
            return json.dumps({"candidates": [
                {"fact": "An outcome.", "source_url": "https://example.gov/o1", "quote": "quoted one"},
                {"fact": "Another outcome.", "source_url": "https://example.gov/o2", "quote": "quoted two"},
            ]})
        return _slot_answer(row["prompt"])

    client = _client()
    answerer = asyncio.create_task(_answer_when_pending(db, respond, count=len(v2.SLOT_ORDER)))
    packet = await v2.run_machine_research_packet(client, "USS Nautilus SSN-571", 1, "title", ["ctx"])
    await answerer
    assert packet["machine"] == "USS Nautilus SSN-571"
    assert len(db.rows) == len(v2.SLOT_ORDER)
    assert all(r["tools"] and "web_search" in r["tools"] for r in db.rows.values())  # agent told to search

    # Re-running the whole stage costs nothing and asks nothing.
    again = await v2.run_machine_research_packet(_client(timeout_seconds=0.05), "USS Nautilus SSN-571", 1, "title", ["ctx"])
    assert again == packet
    assert len(db.rows) == len(v2.SLOT_ORDER)


# ---- MCP tools ---------------------------------------------------------------------------

def _payload(result):
    return json.loads(result["content"][0]["text"])


async def _call(tool, arguments, tenant=TENANT):
    from routes import mcp
    return await mcp._dispatch("tools/call", {"name": tool, "arguments": arguments}, tenant)


def test_relay_tools_are_registered():
    from routes import mcp
    names = {t["name"] for t in mcp.TOOLS}
    assert {"list_pending_llm_requests", "answer_llm_request"} <= names


@pytest.mark.asyncio
async def test_agent_lists_then_answers_and_the_waiting_client_resumes(db):
    client = _client()
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}]
    waiting = asyncio.create_task(client.generate(prompt="find the facts", system_prompt="be exact", tools=tools))
    for _ in range(100):
        listing = _payload(await _call("list_pending_llm_requests", {"video_id": VIDEO}))
        if listing["requests"]:
            break
        await asyncio.sleep(0.01)
    (req,) = listing["requests"]
    assert listing["pending_total"] == 1
    assert req["prompt"] == "find the facts" and req["system_prompt"] == "be exact"
    assert req["web_search"] is True and req["video_id"] == VIDEO and req["status"] == "pending"

    done = await _call("answer_llm_request", {"request_id": req["request_id"], "response": '{"thesis": "x"}'})
    assert done["isError"] is False and _payload(done)["answered"] == 1
    assert await asyncio.wait_for(waiting, 2) == '{"thesis": "x"}'
    assert _payload(await _call("list_pending_llm_requests", {}))["requests"] == []

    fetched = _payload(await _call("list_pending_llm_requests", {"request_id": req["request_id"]}))
    assert fetched["requests"][0]["response"] == '{"thesis": "x"}'


@pytest.mark.asyncio
async def test_answer_tool_batches_and_reports_each_failure(db):
    a = await relay.get_or_create_request(TENANT, VIDEO, fingerprint="d" * 64, stage=None, model="m",
                                          system_prompt="", prompt="a", tools=None, max_tokens=1, temperature=0)
    b = await relay.get_or_create_request(TENANT, VIDEO, fingerprint="e" * 64, stage=None, model="m",
                                          system_prompt="", prompt="b", tools=None, max_tokens=1, temperature=0)
    result = _payload(await _call("answer_llm_request", {"answers": [
        {"request_id": a["id"], "response": "A"},
        {"request_id": b["id"], "response": ""},
        {"request_id": str(uuid.uuid4()), "response": "C"},
    ]}))
    assert result["answered"] == 1
    assert [r["ok"] for r in result["results"]] == [True, False, False]
    assert db.rows[a["id"]]["status"] == "answered" and db.rows[b["id"]]["status"] == "pending"


@pytest.mark.asyncio
async def test_mcp_tools_cannot_see_or_answer_another_workspaces_requests(db):
    row = await relay.get_or_create_request(TENANT, VIDEO, fingerprint="f" * 64, stage=None, model="m",
                                            system_prompt="", prompt="secret prompt", tools=None,
                                            max_tokens=1, temperature=0)
    assert _payload(await _call("list_pending_llm_requests", {}, tenant=OTHER_TENANT))["requests"] == []
    assert (await _call("list_pending_llm_requests", {"request_id": row["id"]}, tenant=OTHER_TENANT))["isError"] is True
    denied = await _call("answer_llm_request", {"request_id": row["id"], "response": "x"}, tenant=OTHER_TENANT)
    assert denied["isError"] is True
    assert db.rows[row["id"]]["status"] == "pending"


@pytest.mark.asyncio
async def test_bad_arguments_are_clean_errors(db):
    assert (await _call("answer_llm_request", {}))["isError"] is True
    assert (await _call("answer_llm_request", {"answers": []}))["isError"] is True
    assert (await _call("list_pending_llm_requests", {"video_id": "nope"}))["isError"] is True
    assert (await _call("list_pending_llm_requests", {"status": "weird"}))["isError"] is True


# ---- executor binding ---------------------------------------------------------------------

def test_executor_binds_relay_to_video_and_ignores_keyed_clients():
    from types import SimpleNamespace
    import pipeline_executor as pe

    ex = pe.PipelineExecutor(TENANT)
    ex._bind_agent_relay(VIDEO)  # not initialised yet: must not raise

    relay = relay_client.AgentRelayClient(TENANT)
    ex._pipeline = SimpleNamespace(anthropic=relay)
    ex._bind_agent_relay(VIDEO)
    assert relay.video_id == VIDEO and relay.should_cancel is None

    async def cancelled():
        return True
    ex._bind_agent_relay(OTHER_VIDEO, cancelled)
    assert relay.video_id == OTHER_VIDEO and relay.should_cancel is cancelled
    ex._bind_agent_relay(VIDEO)  # a later bind without a cancel hook keeps the armed one
    assert relay.should_cancel is cancelled

    ex._pipeline = SimpleNamespace(anthropic=SimpleNamespace(generate=None))  # a normal keyed client
    ex._bind_agent_relay(VIDEO)
    ex._pipeline = SimpleNamespace(anthropic=None)
    ex._bind_agent_relay(VIDEO)
