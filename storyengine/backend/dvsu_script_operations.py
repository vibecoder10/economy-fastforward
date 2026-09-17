"""Save each DVSU model response before parsing; never resubmit uncertain work."""
from __future__ import annotations
import hashlib
import inspect
import json
from database import fetch_one
from factual_source_search import SourceDiscoveryError


class ScriptOperationError(SourceDiscoveryError):
    def __init__(self, message, *, machine, operation_id, code='reconciliation_required'):
        super().__init__(message, code=code, retryable=False, attempts=1,
                         next_action='reconcile', machine=machine,
                         receipt={'operation_id': operation_id})
        self.stage = 'script'
        self.saved_progress = True


class DurableScriptClient:
    """A scoped generate proxy. Other consumers retain their existing client policy."""
    def __init__(self, client, tenant_id, video_id, machine, input_fingerprint, guard):
        self.client, self.tenant_id, self.video_id = client, tenant_id, video_id
        self.machine, self.input_fingerprint, self.guard = machine, input_fingerprint, guard

    async def generate(self, **kwargs):
        request = json.dumps(kwargs, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        operation_id = hashlib.sha256(json.dumps([str(self.tenant_id),str(self.video_id),self.machine,
            self.input_fingerprint,request,'evidence-led-v1']).encode()).hexdigest()
        args = (self.tenant_id, self.video_id, operation_id)
        saved = await fetch_one('SELECT status,response FROM dvsu_script_operations WHERE tenant_id=$1 AND video_id=$2 AND operation_id=$3', *args)
        if saved:
            if saved['status'] == 'received' and isinstance(saved.get('response'), str):
                return saved['response']
            raise ScriptOperationError('A saved writing request is unresolved. Reconcile it before another paid call.', machine=self.machine, operation_id=operation_id)
        allowed = self.guard()
        if inspect.isawaitable(allowed): allowed = await allowed
        if not allowed:
            raise ScriptOperationError('Writing stopped because the budget, cancellation, roster or saved evidence changed.', machine=self.machine, operation_id=operation_id, code='guard')
        claimed = await fetch_one('''INSERT INTO dvsu_script_operations
            (tenant_id,video_id,operation_id,machine,input_fingerprint,status,request_metadata)
            VALUES ($1,$2,$3,$4,$5,'submitted',$6::jsonb)
            ON CONFLICT (tenant_id,video_id,operation_id) DO NOTHING RETURNING operation_id''',
            *args, self.machine, self.input_fingerprint,
            json.dumps({'model':kwargs.get('model'),'max_tokens':kwargs.get('max_tokens'),
                        'request_bytes':len(request.encode()),'no_resubmit':True}))
        if not claimed:
            raise ScriptOperationError('This writing request is already owned by another execution; no duplicate was sent.',machine=self.machine,operation_id=operation_id)
        try:
            response = await self.client.generate(**kwargs, no_resubmit=True)
        except Exception as exc:
            # The submitted row is deliberately retained: provider receipt may
            # be lost and there is no safe automatic duplicate submission.
            raise ScriptOperationError('The writing provider did not return a confirmed response. Reconcile the saved request before retrying.',machine=self.machine,operation_id=operation_id) from exc
        if not isinstance(response, str):
            raise ScriptOperationError('The writing provider returned an unsupported response; the request is retained for reconciliation.',machine=self.machine,operation_id=operation_id)
        try:
            stored = await fetch_one('''UPDATE dvsu_script_operations SET status='received',response=$4,updated_at=now()
                WHERE tenant_id=$1 AND video_id=$2 AND operation_id=$3 AND status='submitted'
                RETURNING operation_id''', *args, response)
        except Exception as exc:
            raise ScriptOperationError('The writing response could not be checkpointed. Reconcile the saved request before retrying.', machine=self.machine, operation_id=operation_id) from exc
        if not stored:
            raise ScriptOperationError('The writing response could not be checkpointed. Reconcile the saved request before retrying.',machine=self.machine,operation_id=operation_id)
        return response
