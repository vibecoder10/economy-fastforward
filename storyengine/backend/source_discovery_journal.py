"""CAS journal for Kie source searches; evidence and operation receipts are separate."""
from __future__ import annotations
import hashlib
import json
import math
from database import fetch_one


def operation_key(tenant_id, video_id, machine, title, parameters):
    identity = [str(tenant_id), str(video_id), machine, title, parameters, 'source-discovery-v1']
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class SourceDiscoveryJournal:
    def __init__(self, tenant_id, video_id, operation_id, state, revision):
        self.tenant_id, self.video_id, self.operation_id = tenant_id, video_id, operation_id
        self.state, self.revision = state, revision

    @classmethod
    async def open(cls, tenant_id, video_id, machine, title, parameters):
        key = operation_key(tenant_id, video_id, machine, title, parameters)
        row = await fetch_one('''INSERT INTO source_discovery_operations
            (tenant_id, video_id, operation_id, machine, state)
            VALUES ($1,$2,$3,$4,'{}'::jsonb)
            ON CONFLICT (tenant_id,video_id,operation_id) DO UPDATE
            SET operation_id=EXCLUDED.operation_id
            RETURNING state,revision''', tenant_id, video_id, key, machine)
        if not row:
            raise RuntimeError('Source discovery journal could not be opened; no request was sent')
        state = row['state']
        if isinstance(state, str): state = json.loads(state)
        state = dict(state)
        state.setdefault('operation_id', key)
        journal = cls(tenant_id, video_id, key, state, row['revision'])
        await journal._record_usage(state)
        return journal

    async def checkpoint(self, state):
        # Exactly one concurrent reader can advance a revision to submitted.
        row = await fetch_one('''UPDATE source_discovery_operations SET state=$4::jsonb,
            revision=revision+1,updated_at=now()
            WHERE tenant_id=$1 AND video_id=$2 AND operation_id=$3 AND revision=$5
            RETURNING revision''', self.tenant_id, self.video_id, self.operation_id,
            json.dumps(state, ensure_ascii=False), self.revision)
        if not row:
            raise RuntimeError('Source discovery checkpoint conflict; reconcile the saved operation before retrying')
        self.revision = row['revision']
        self.state.clear(); self.state.update(state)
        await self._record_usage(state)
        return True

    async def _record_usage(self, state):
        # A confirmed invalid response can still cost money. Account for every
        # received attempt before permitting another one; failed DB writes stop.
        receipts = list(state.get('receipts') or []) + [state.get('receipt') or {}]
        for receipt in receipts:
            request_id = receipt.get('request_id')
            credits = receipt.get('credits_consumed')
            if not request_id or credits is None:
                continue
            try: credits = float(credits)
            except (TypeError, ValueError): continue
            if not math.isfinite(credits) or credits < 0: continue
            from factual_source_search import USD_PER_CREDIT, MODEL
            row = await fetch_one("""WITH added AS (
                INSERT INTO generation_ledger
                    (tenant_id,video_id,stage,model,units,unit_cost,actual_cost,kie_task_id)
                VALUES ($1,$2,'research',$3,$4,$5,$6,$7)
                ON CONFLICT (video_id,stage,kie_task_id) WHERE kie_task_id IS NOT NULL DO NOTHING
                RETURNING actual_cost
            ) UPDATE videos SET total_cost =
                (SELECT COALESCE(SUM(actual_cost),0) FROM generation_ledger WHERE tenant_id=$1 AND video_id=$2)
                + (SELECT COALESCE(SUM(actual_cost),0) FROM added)
              WHERE tenant_id=$1 AND id=$2 RETURNING total_cost""",
                self.tenant_id, self.video_id, 'kie/' + MODEL, credits,
                USD_PER_CREDIT, credits * USD_PER_CREDIT, str(request_id))
            if not row:
                raise RuntimeError('Source usage could not be checkpointed; no further request is permitted')
