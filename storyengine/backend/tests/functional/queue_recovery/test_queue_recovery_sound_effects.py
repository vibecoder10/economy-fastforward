"""Recovery test: sound_effects stage — idempotency and error propagation."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from job_queue import enqueue_stage, make_job_id
from worker import arq_run_sound_effects


@pytest.mark.asyncio
async def test_sound_effects_idempotency_key_prevents_duplicate():
    """Same job_id returns None on second enqueue — no double-dispatch."""
    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(
        side_effect=[MagicMock(job_id="sound_effects:vid1:1"), None]
    )

    job_id_1 = await enqueue_stage(fake_pool, "sound_effects", "vid1", "tenant1", attempt=1)
    job_id_2 = await enqueue_stage(fake_pool, "sound_effects", "vid1", "tenant1", attempt=1)

    assert job_id_1 == "sound_effects:vid1:1"
    assert job_id_2 is None
    assert fake_pool.enqueue_job.call_count == 2


def test_sound_effects_retry_uses_incremented_attempt():
    """Retry enqueue uses attempt+1 so idempotency key differs."""
    key_1 = make_job_id("sound_effects", "vid1", 1)
    key_2 = make_job_id("sound_effects", "vid1", 2)
    assert key_1 != key_2


@pytest.mark.asyncio
async def test_sound_effects_worker_reraises_on_failure():
    """Worker re-raises exceptions so arq can retry."""
    ctx = {"job_try": 1}
    with patch("pipeline_executor.PipelineExecutor") as MockExec:
        MockExec.return_value.run_sound_effects = AsyncMock(
            side_effect=RuntimeError("API timeout")
        )
        with patch("task_store.db_persist_task", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="API timeout"):
                await arq_run_sound_effects(ctx, "vid1", "tenant1", attempt=1)


@pytest.mark.asyncio
async def test_sound_effects_persists_completed_status():
    """background_tasks row updated to 'completed' on success."""
    ctx = {"job_try": 1}
    with patch("pipeline_executor.PipelineExecutor") as MockExec:
        MockExec.return_value.run_sound_effects = AsyncMock(
            return_value={"status": "completed"}
        )
        with patch("task_store.db_persist_task", new_callable=AsyncMock) as mock_persist:
            result = await arq_run_sound_effects(ctx, "vid1", "tenant1", attempt=1)

        assert result["status"] == "completed"
        # Should have been called at least twice: running + completed
        assert mock_persist.call_count >= 2
        completed_call = mock_persist.call_args_list[-1]
        # db_persist_task(tenant_id, video_id, task_type, status, ...) — index 3 is status
        assert completed_call.args[3] == "completed"
