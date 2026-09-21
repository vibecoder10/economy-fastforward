-- Agent LLM relay (docs/agent-llm-relay-2026-09-21/DESIGN.md).
-- When a workspace is opted in (tenants.agent_llm_relay), the pipeline's model calls are parked here as
-- `pending` rows; the connected MCP agent answers them and the waiting stage resumes.
-- An answered row is also the replay cache: an identical request (same fingerprint, same
-- tenant + video) is served from `response_text` and never asks the agent twice.

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS agent_llm_relay BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS agent_llm_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    video_id UUID,
    -- 'tenant' when the call is not tied to a video; else the video uuid. Kept as a plain
    -- column so the uniqueness rule below needs no expression index / NULL special-casing.
    scope TEXT NOT NULL,
    fingerprint TEXT NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    stage TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','answered')),
    model TEXT,
    system_prompt TEXT,
    prompt TEXT NOT NULL,
    tools JSONB,
    max_tokens INTEGER,
    temperature DOUBLE PRECISION,
    response_text TEXT,
    answer_count INTEGER NOT NULL DEFAULT 0,
    answered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, scope, fingerprint),
    FOREIGN KEY (tenant_id, video_id) REFERENCES videos(tenant_id, id) ON DELETE CASCADE,
    CHECK (status <> 'answered' OR response_text IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS agent_llm_requests_pending_idx
    ON agent_llm_requests (tenant_id, created_at) WHERE status = 'pending';

ALTER TABLE agent_llm_requests ENABLE ROW LEVEL SECURITY;
-- Backend-only; no authenticated/anon PostgREST policies (prompts can embed prior research text).
