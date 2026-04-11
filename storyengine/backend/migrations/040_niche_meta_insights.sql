-- Migration 040: Niche meta-insights table for second-order distillation
-- Stores cross-video meta-analysis: niche patterns, timing strategy, combination insights.
-- One row per tenant (upserted on each analysis cycle).

CREATE TABLE IF NOT EXISTS niche_meta_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    generated_at TIMESTAMPTZ DEFAULT now(),
    sample_size INTEGER DEFAULT 0,
    meta_report TEXT,
    structured_insights JSONB,
    top_hook_types JSONB,
    top_thumbnail_patterns JSONB,
    top_title_structures JSONB,
    optimal_timing JSONB,
    niche_signature JSONB
);

-- One meta-insight per tenant (upsert target)
CREATE UNIQUE INDEX IF NOT EXISTS idx_nmi_tenant_unique
    ON niche_meta_insights(tenant_id);

-- RLS
ALTER TABLE niche_meta_insights ENABLE ROW LEVEL SECURITY;

CREATE POLICY niche_meta_insights_tenant_isolation ON niche_meta_insights
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
