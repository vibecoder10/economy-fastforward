"""Focused contracts for idempotent, durable title-list production."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest

from routes import queue


@pytest.fixture(autouse=True)
def _provider_pause_is_separately_tested(monkeypatch):
    monkeypatch.setattr(queue, "sync_provider_pause", AsyncMock(return_value=None))
    monkeypatch.setattr(queue, "get_queue_pause", AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_repeat_title_intake_is_idempotent_with_normalized_key(monkeypatch):
    monkeypatch.setattr(queue, "fetch_one", AsyncMock(return_value={"p": 0}))
    execute = AsyncMock(side_effect=["INSERT 0 1", "INSERT 0 0"])
    monkeypatch.setattr(queue, "execute", execute)

    count = await queue.add_queue_items(
        "tenant-1",
        [{"title": "  The   Same Title "}, {"title": "the same title"}],
        continuous=True,
        required_render_mode="static_docu",
    )

    assert count == 1
    first, second = execute.await_args_list
    assert "lower(regexp_replace(trim($8)" in first.args[0]
    assert first.args[9:] == (True, "static_docu", "render_only", None, None)
    assert "ON CONFLICT" in first.args[0]


@pytest.mark.asyncio
async def test_add_queue_items_stores_request_level_video_length(monkeypatch):
    monkeypatch.setattr(queue, "fetch_one", AsyncMock(return_value={"p": 0}))
    execute = AsyncMock(return_value="INSERT 0 1")
    monkeypatch.setattr(queue, "execute", execute)

    count = await queue.add_queue_items(
        "tenant-1", [{"title": "A Title"}], video_length_minutes=20,
    )

    assert count == 1
    args = execute.await_args_list[0].args
    assert args[-1] == 20.0


@pytest.mark.asyncio
async def test_add_queue_items_per_item_length_overrides_request_default(monkeypatch):
    monkeypatch.setattr(queue, "fetch_one", AsyncMock(return_value={"p": 0}))
    execute = AsyncMock(return_value="INSERT 0 1")
    monkeypatch.setattr(queue, "execute", execute)

    await queue.add_queue_items(
        "tenant-1",
        [{"title": "A Title", "video_length_minutes": 45}],
        video_length_minutes=20,
    )

    args = execute.await_args_list[0].args
    assert args[-1] == 45.0


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_length", [0, -5, float("nan"), float("inf")])
async def test_add_queue_items_rejects_invalid_video_length(monkeypatch, bad_length):
    monkeypatch.setattr(queue, "fetch_one", AsyncMock(return_value={"p": 0}))
    monkeypatch.setattr(queue, "execute", AsyncMock(return_value="INSERT 0 1"))

    with pytest.raises(queue.HTTPException) as exc_info:
        await queue.add_queue_items(
            "tenant-1", [{"title": "A Title"}], video_length_minutes=bad_length,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_prepare_video_insert_includes_video_length(monkeypatch):
    statements = []

    class Conn:
        async def fetchrow(self, query, *args):
            statements.append((query, args))
            return {"id": "item-1", "video_id": None}

        async def execute(self, query, *args):
            statements.append((query, args))
            return "INSERT 0 1"

        def transaction(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    conn = Conn()

    class Pool:
        def acquire(self):
            return conn

    monkeypatch.setattr(queue, "get_pool", AsyncMock(return_value=Pool()))
    monkeypatch.setattr(
        "routes.projects._get_or_create_project",
        AsyncMock(return_value={"id": "project-1"}),
    )

    video_id, created = await queue._prepare_video(
        "tenant-1",
        {"id": "item-1", "title": "Title", "framework_angle": None,
         "writer_guidance": None, "video_length_minutes": 20},
        via="autopilot_queue",
    )

    assert created is True
    assert video_id
    insert_query, insert_args = next(
        (q, a) for q, a in statements if "INSERT INTO videos" in q
    )
    assert "video_length_minutes" in insert_query
    assert 20 in insert_args


@pytest.mark.asyncio
async def test_video_reservation_and_creation_share_one_transaction(monkeypatch):
    statements = []

    class Conn:
        async def fetchrow(self, query, *args):
            statements.append((query, args))
            return {"id": "item-1", "video_id": None}

        async def execute(self, query, *args):
            statements.append((query, args))
            return "INSERT 0 1"

        def transaction(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    conn = Conn()

    class Pool:
        def acquire(self):
            return conn

    monkeypatch.setattr(queue, "get_pool", AsyncMock(return_value=Pool()))
    monkeypatch.setattr(
        "routes.projects._get_or_create_project",
        AsyncMock(return_value={"id": "project-1"}),
    )

    video_id, created = await queue._prepare_video(
        "tenant-1",
        {"id": "item-1", "title": "Title", "framework_angle": None,
         "writer_guidance": None},
        via="autopilot_queue",
    )

    assert created is True
    assert video_id
    assert any("INSERT INTO videos" in query for query, _ in statements)
    assert any("UPDATE production_queue SET video_id" in query for query, _ in statements)


@pytest.mark.asyncio
async def test_continuous_queue_bypasses_cadence_but_keeps_one_active_lane(monkeypatch):
    monkeypatch.setattr(queue, "_reconcile_queue_items", AsyncMock())

    async def fetch_one(query, *args):
        if "SELECT id, continuous" in query:
            return {"id": "item-1", "continuous": True}
        if "autopilot_config" in query:
            return {"production_interval_days": 30}
        if "GREATEST" in query:
            return {"t": "recent"}
        if "UPDATE production_queue SET status = 'launched'" in query:
            return {"id": "item-1", "title": "Title", "continuous": True}
        if "status IN ('launched', 'dispatching', 'running')" in query:
            return None
        raise AssertionError(query)

    launch = AsyncMock(return_value={"status": "launched", "continuous": True})
    monkeypatch.setattr(queue, "fetch_one", fetch_one)
    monkeypatch.setattr(
        queue, "_claim_next",
        AsyncMock(return_value={"id": "item-1", "title": "Title", "continuous": True}),
    )
    monkeypatch.setattr(queue, "launch_queue_item", launch)
    pool = object()

    result = await queue.auto_produce_next("tenant-1", arq_pool=pool)

    assert result["status"] == "launched"
    launch.assert_awaited_once_with(
        "tenant-1", ANY, arq_pool=pool, via="autopilot_queue"
    )


@pytest.mark.asyncio
async def test_durable_dispatch_claims_main_and_targets_render_finish(monkeypatch):
    acquire = AsyncMock(return_value=True)
    release = AsyncMock()
    enqueue = AsyncMock()
    monkeypatch.setattr("generation_claims.acquire", acquire)
    monkeypatch.setattr("generation_claims.release_owned", release)
    monkeypatch.setattr("routes.pipeline._enqueue_or_fallback", enqueue)
    monkeypatch.setattr(queue, "execute", AsyncMock(return_value="UPDATE 1"))

    await queue._dispatch_durable_autobuild(
        "tenant-1",
        {"id": "item-1", "title": "DVSU Title", "attempt_count": 0,
         "delivery_mode": "youtube_unlisted", "delivery_channel_id": "UC-owner"},
        "video-1",
        object(),
    )

    acquire.assert_awaited_once()
    assert acquire.await_args.args[:3] == ("tenant-1", "video-1", "main")
    assert enqueue.await_args.args[2:5] == ("autobuild", "video-1", "tenant-1")
    assert enqueue.await_args.kwargs["durable_only"] is True
    assert enqueue.await_args.kwargs["target"] == "finish"
    assert enqueue.await_args.kwargs["delivery_mode"] == "youtube_unlisted"
    assert enqueue.await_args.kwargs["expected_channel_id"] == "UC-owner"
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_queue_fails_before_video_or_paid_work(monkeypatch):
    unclaim = AsyncMock()
    monkeypatch.setattr(queue, "_unclaim", unclaim)
    prepare = AsyncMock()
    monkeypatch.setattr(queue, "_prepare_video", prepare)

    with pytest.raises(Exception) as exc_info:
        await queue.launch_queue_item(
            "tenant-1", {"id": "item-1", "title": "Title"}, arq_pool=None
        )

    assert getattr(exc_info.value, "status_code", None) == 503
    unclaim.assert_awaited_once_with("tenant-1", "item-1")
    prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_projects_render_and_terminal_task_outcomes(monkeypatch):
    execute = AsyncMock(return_value="UPDATE 1")
    @asynccontextmanager
    async def locked(tenant_id):
        yield SimpleNamespace(execute=execute)
    monkeypatch.setattr(queue, "_locked_queue_connection", locked)

    await queue._reconcile_queue_items("tenant-1")

    assert execute.await_count == 3
    assert "SET status = 'completed'" in execute.await_args_list[0].args[0]
    completion_sql = execute.await_args_list[0].args[0]
    assert "q.delivery_mode = 'render_only'" in completion_sql
    assert "queue_delivery_receipt->>'status' = 'verified'" in completion_sql
    assert "queue_delivery_receipt->>'channel_id' = q.delivery_channel_id" in completion_sql
    assert "queue_delivery_receipt->>'privacy' = 'unlisted'" in completion_sql
    assert "v.upload_status = 'uploaded'" in completion_sql
    assert "task_type = 'autobuild'" in execute.await_args_list[1].args[0]
    assert "q.delivery_mode = 'youtube_unlisted'" in execute.await_args_list[1].args[0]
    assert "COALESCE(v.queue_delivery_receipt->>'status' = 'verified', false)" in execute.await_args_list[1].args[0]
    assert "ELSE 'failed'" in execute.await_args_list[1].args[0]
    assert "q.attempt_count < 3" in execute.await_args_list[1].args[0]
    assert execute.await_args_list[1].args[3:] == (
        queue.QUEUE_QUALITY_ERROR_PATTERN,
        queue.QUEUE_TRANSIENT_ERROR_PATTERN,
    )
    assert "b.created_at >= q.launched_at" in execute.await_args_list[1].args[0]
    assert "status IN ('launched', 'dispatching')" in execute.await_args_list[2].args[0]
    assert "status IN ('pending', 'running')" in execute.await_args_list[2].args[0]


@pytest.mark.parametrize(
    "message",
    [
        "Research gate failed; not advancing to scripting: Roster validation failed",
        (
            "Research found a roster coverage or scope issue, so production stopped "
            "before scripting. Review the research roster, correct the issue, and retry."
        ),
        (
            "Research for one or more roster entries did not meet the source requirements, "
            "so production stopped before scripting. Review the blocked research entries and retry."
        ),
        "Roster source validation failed because source provider unavailable; retry.",
        "Quality gate failed; retry after correcting the evidence.",
        "Please retry after editorial review.",
        "Anthropic credit balance is too low; retry after adding funds.",
    ],
)
def test_quality_provider_and_advisory_retry_messages_are_not_transient(message):
    assert queue._queue_failure_is_transient(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "Worker interrupted while acknowledging the durable job",
        "Redis connection reset during dispatch",
        "Upstream service temporarily unavailable",
        "Task timed out after 1800 seconds",
    ],
)
def test_infrastructure_failures_remain_transient(message):
    assert queue._queue_failure_is_transient(message) is True


@pytest.mark.asyncio
async def test_retry_reuses_reserved_video_and_stops_after_three_attempts(monkeypatch):
    real_dispatch = queue._dispatch_durable_autobuild
    prepare = AsyncMock(return_value=("video-1", False))
    monkeypatch.setattr(queue, "_prepare_video", prepare)
    monkeypatch.setattr(queue, "fetch_all", AsyncMock(return_value=[]))
    monkeypatch.setattr("static_docu.static_mode_for_tenant", AsyncMock(return_value=False))
    monkeypatch.setattr(queue, "execute", AsyncMock(return_value="UPDATE 1"))
    monkeypatch.setattr("drain_mode.assert_accepting_new_work", AsyncMock())
    monkeypatch.setattr(
        "autopilot_dial.get_autopilot_dial",
        AsyncMock(return_value=SimpleNamespace(kill_switch_tripped_at=None)),
    )
    monkeypatch.setattr(
        "autopilot_dial.check_weekly_budget", AsyncMock(return_value=(True, 0, 10))
    )
    check_plan = AsyncMock()
    increment = AsyncMock()
    monkeypatch.setattr("routes.billing.check_plan_limits", check_plan)
    monkeypatch.setattr("routes.billing.increment_usage", increment)
    monkeypatch.setattr("routes.script_templates.apply_default_template", AsyncMock())
    monkeypatch.setattr("channel_format.apply_format_defaults", AsyncMock())
    monkeypatch.setattr("channel_format.apply_machine_script_contract", AsyncMock())
    monkeypatch.setattr("routes.characters.apply_locked_cast", AsyncMock())
    dispatch = AsyncMock()
    monkeypatch.setattr(queue, "_dispatch_durable_autobuild", dispatch)
    item = {
        "id": "item-1", "title": "Title", "video_id": "video-1",
        "attempt_count": 2, "continuous": True,
    }

    result = await queue.launch_queue_item("tenant-1", item, arq_pool=object())

    assert result["video_id"] == "video-1"
    prepare.assert_awaited_once()
    check_plan.assert_not_awaited()
    increment.assert_not_awaited()
    dispatch.assert_awaited_once_with("tenant-1", item, "video-1", ANY)

    monkeypatch.setattr("generation_claims.acquire", AsyncMock(return_value=True))
    with pytest.raises(Exception) as exc_info:
        await real_dispatch(
            "tenant-1", {**item, "attempt_count": 3}, "video-1", object()
        )
    assert getattr(exc_info.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_continuous_queue_runs_with_autopilot_disabled(monkeypatch):
    import main
    import autopilot_dial
    import routes.queue as queue_module

    monkeypatch.setattr(main, "_is_autopilot_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(main, "fetch_one", AsyncMock(return_value={"x": 1}))
    monkeypatch.setattr(
        autopilot_dial, "get_autopilot_dial",
        AsyncMock(return_value=SimpleNamespace(
            kill_switch_tripped_at=None, dial_level="propose_only",
            weekly_budget_cap=None,
        )),
    )
    monkeypatch.setattr(
        autopilot_dial, "check_weekly_budget", AsyncMock(return_value=(True, 0, None))
    )
    launch = AsyncMock(return_value={"status": "launched", "continuous": True})
    monkeypatch.setattr(queue_module, "auto_produce_next", launch)

    result = await main._produce_for_tenant("tenant-1", arq_pool=object())

    assert result["status"] == "launched"
    launch.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabled_autopilot_never_falls_through_after_continuous_queue_tick(monkeypatch):
    import main
    import autopilot_dial
    import autopilot_launch
    import routes.queue as queue_module

    monkeypatch.setattr(main, "_is_autopilot_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(main, "fetch_one", AsyncMock(return_value={"x": 1}))
    monkeypatch.setattr(
        autopilot_dial, "get_autopilot_dial",
        AsyncMock(return_value=SimpleNamespace(
            kill_switch_tripped_at=None, dial_level="propose_only",
            weekly_budget_cap=None,
        )),
    )
    monkeypatch.setattr(
        autopilot_dial, "check_weekly_budget", AsyncMock(return_value=(True, 0, None))
    )
    monkeypatch.setattr(queue_module, "auto_produce_next", AsyncMock(return_value=None))
    candidate = AsyncMock()
    monkeypatch.setattr(autopilot_launch, "auto_launch_best_candidate", candidate)

    assert await main._produce_for_tenant("tenant-1", arq_pool=object()) is None
    candidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_takes_advisory_lock_before_fresh_candidate_snapshot(monkeypatch):
    calls = []

    class Conn:
        async def execute(self, query, *args):
            calls.append(("execute", query, args))

        async def fetchrow(self, query, *args):
            calls.append(("fetchrow", query, args))
            return {"id": "item-1"}

        def transaction(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class Pool:
        def acquire(self):
            return Conn()

    monkeypatch.setattr(queue, "get_pool", AsyncMock(return_value=Pool()))

    row = await queue._claim_next("tenant-1")

    assert row == {"id": "item-1"}
    assert [kind for kind, _, _ in calls] == ["execute", "fetchrow"]
    assert "pg_advisory_xact_lock" in calls[0][1]
    candidate_sql = calls[1][1]
    assert "NOT EXISTS (\n                           SELECT 1 FROM production_queue managed" in candidate_sql
    assert "generation_claims" in candidate_sql
    assert "interval '7 days'" not in candidate_sql


@pytest.mark.asyncio
async def test_title_patch_updates_normalized_key_and_reports_duplicate(monkeypatch):
    class DuplicateTitle(Exception):
        sqlstate = "23505"

    fetch = AsyncMock(side_effect=DuplicateTitle())
    monkeypatch.setattr(queue, "fetch_one", fetch)

    with pytest.raises(Exception) as exc_info:
        await queue.patch_queue_item(
            "item-1", queue.QueuePatch(title="  Existing   Title "), "tenant-1"
        )

    assert getattr(exc_info.value, "status_code", None) == 409
    assert "item_key = lower(regexp_replace" in fetch.await_args.args[0]


@pytest.mark.asyncio
async def test_continuous_intake_returns_saved_policy_block(monkeypatch):
    monkeypatch.setattr(queue, "add_queue_items", AsyncMock(return_value=2))
    monkeypatch.setattr(
        queue, "auto_produce_next",
        AsyncMock(side_effect=queue.HTTPException(status_code=409, detail="Budget cap reached")),
    )
    execute = AsyncMock(return_value="UPDATE 2")
    monkeypatch.setattr(queue, "execute", execute)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq=object())))

    result = await queue.add_to_queue(
        queue.QueueAddRequest(
            items=[queue.QueueItemIn(title="One"), queue.QueueItemIn(title="Two")],
            continuous=True, required_render_mode="static_docu",
        ),
        request,
        "tenant-1",
    )

    assert result == {"status": "queued", "count": 2, "message": "Budget cap reached"}
    assert "SET last_error=$2" in execute.await_args.args[0]


@pytest.mark.asyncio
async def test_continuous_intake_wakes_sleeping_scheduler(monkeypatch):
    monkeypatch.setattr(queue, "add_queue_items", AsyncMock(return_value=1))
    monkeypatch.setattr(queue, "auto_produce_next", AsyncMock(return_value=None))

    class Wakeup:
        def __init__(self):
            self.set_calls = 0

        def set(self):
            self.set_calls += 1

    wakeup = Wakeup()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(arq=object(), queue_wakeup=wakeup)
        )
    )

    result = await queue.add_to_queue(
        queue.QueueAddRequest(
            items=[queue.QueueItemIn(title="One")], continuous=True,
            required_render_mode="static_docu",
        ),
        request,
        "tenant-1",
    )

    assert result == {"status": "queued", "count": 1}
    assert wakeup.set_calls == 1


@pytest.mark.asyncio
async def test_unlisted_intake_snapshots_only_stored_connected_channel(monkeypatch):
    fetch = AsyncMock(side_effect=[
        {"youtube_channel_id": "UC-owner", "youtube_refresh_token": "stored-token"},
        {"p": 0},
    ])
    execute = AsyncMock(return_value="INSERT 0 1")
    monkeypatch.setattr(queue, "fetch_one", fetch)
    monkeypatch.setattr(queue, "execute", execute)

    count = await queue.add_queue_items(
        "tenant-1", [{"title": "Deliver Me"}],
        delivery_mode="youtube_unlisted",
    )

    assert count == 1
    assert execute.await_args.args[-3:-1] == ("youtube_unlisted", "UC-owner")
    assert "stored-token" not in execute.await_args.args


@pytest.mark.asyncio
async def test_unlisted_launch_rejects_disconnected_snapshot_before_video_work(monkeypatch):
    monkeypatch.setattr(queue, "_unclaim", AsyncMock())
    monkeypatch.setattr("drain_mode.assert_accepting_new_work", AsyncMock())
    monkeypatch.setattr(
        "autopilot_dial.get_autopilot_dial",
        AsyncMock(return_value=SimpleNamespace(
            kill_switch_tripped_at=None, dial_level="propose_only",
            weekly_budget_cap=None,
        )),
    )
    monkeypatch.setattr(
        queue, "fetch_one",
        AsyncMock(return_value={"youtube_channel_id": "UC-other", "youtube_refresh_token": "token"}),
    )
    prepare = AsyncMock()
    monkeypatch.setattr(queue, "_prepare_video", prepare)

    with pytest.raises(Exception) as exc_info:
        await queue.launch_queue_item(
            "tenant-1",
            {"id": "item-1", "title": "Title", "delivery_mode": "youtube_unlisted",
             "delivery_channel_id": "UC-owner"},
            arq_pool=object(),
        )

    assert getattr(exc_info.value, "status_code", None) == 409
    prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_unlisted_intake_requires_connected_channel_before_insert(monkeypatch):
    monkeypatch.setattr(
        queue, "fetch_one",
        AsyncMock(return_value={"youtube_channel_id": "UC-owner", "youtube_refresh_token": None}),
    )
    execute = AsyncMock()
    monkeypatch.setattr(queue, "execute", execute)

    with pytest.raises(Exception) as exc_info:
        await queue.add_queue_items(
            "tenant-1", [{"title": "Deliver Me"}],
            delivery_mode="youtube_unlisted",
        )

    assert getattr(exc_info.value, "status_code", None) == 409
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_c55_full_auto_promotes_only_scheduler_noncontinuous_default(monkeypatch):
    profile = AsyncMock(return_value={
        "youtube_channel_id": "UC-legacy", "youtube_refresh_token": "token",
    })
    execute = AsyncMock(return_value="UPDATE 1")
    monkeypatch.setattr(queue, "fetch_one", profile)
    monkeypatch.setattr(queue, "execute", execute)
    dial = SimpleNamespace(dial_level="full_auto", weekly_budget_cap=25)
    base = {"id": "item-1", "delivery_mode": "render_only"}

    promoted = await queue._resolve_launch_delivery(
        "tenant-1", {**base, "continuous": False},
        via="autopilot_queue", dial=dial,
    )
    continuous = await queue._resolve_launch_delivery(
        "tenant-1", {**base, "continuous": True},
        via="autopilot_queue", dial=dial,
    )
    manual = await queue._resolve_launch_delivery(
        "tenant-1", {**base, "continuous": False},
        via="queue", dial=dial,
    )

    assert promoted["delivery_mode"] == "youtube_unlisted"
    assert promoted["delivery_channel_id"] == "UC-legacy"
    assert continuous.get("delivery_mode") == "render_only"
    assert manual.get("delivery_mode") == "render_only"
    profile.assert_awaited_once()
    assert "SET delivery_mode='youtube_unlisted'" in execute.await_args.args[0]


@pytest.mark.asyncio
async def test_add_to_queue_rejects_invalid_video_length(monkeypatch):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq=None)))

    with pytest.raises(queue.HTTPException) as exc_info:
        await queue.add_to_queue(
            queue.QueueAddRequest(
                items=[queue.QueueItemIn(title="One")],
                video_length_minutes=0,
            ),
            request,
            "tenant-1",
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_add_to_queue_enforces_plan_length_cap(monkeypatch):
    import routes.billing as billing

    cap = AsyncMock(side_effect=queue.HTTPException(status_code=402, detail="Upgrade required"))
    monkeypatch.setattr(billing, "enforce_video_length_cap", cap)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq=None)))

    with pytest.raises(queue.HTTPException) as exc_info:
        await queue.add_to_queue(
            queue.QueueAddRequest(
                items=[queue.QueueItemIn(title="One")],
                video_length_minutes=60,
            ),
            request,
            "tenant-1",
        )

    assert exc_info.value.status_code == 402
    cap.assert_awaited()


@pytest.mark.asyncio
async def test_add_to_queue_passes_video_length_through_to_add_queue_items(monkeypatch):
    import routes.billing as billing

    monkeypatch.setattr(billing, "enforce_video_length_cap", AsyncMock())
    add_items = AsyncMock(return_value=1)
    monkeypatch.setattr(queue, "add_queue_items", add_items)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq=None)))

    await queue.add_to_queue(
        queue.QueueAddRequest(
            items=[queue.QueueItemIn(title="One")],
            video_length_minutes=20,
        ),
        request,
        "tenant-1",
    )

    assert add_items.await_args.kwargs["video_length_minutes"] == 20
