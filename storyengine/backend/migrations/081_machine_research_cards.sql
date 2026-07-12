-- Compact, tenant-isolated checkpoints for one locked machine's research.
-- videos.research_payload.unit_research_cards remains dual-written for compatibility.
BEGIN;

-- This one-time index build may briefly lock the small videos table.  That is
-- preferable here to a non-transactional CONCURRENTLY migration because the
-- composite key must exist before the child FK is created atomically.
CREATE UNIQUE INDEX IF NOT EXISTS videos_tenant_id_id_uidx ON videos (tenant_id, id);

CREATE TABLE machine_research_cards (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  video_id UUID NOT NULL,
  machine_key TEXT NOT NULL CHECK (btrim(machine_key) <> ''),
  machine_name TEXT NOT NULL,
  roster_index INTEGER NOT NULL CHECK (roster_index > 0),
  card JSONB NOT NULL CHECK (jsonb_typeof(card) = 'object'),
  validation JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(validation) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, video_id, machine_key),
  UNIQUE (tenant_id, video_id, roster_index),
  FOREIGN KEY (tenant_id, video_id) REFERENCES videos(tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS machine_research_cards_video_order_idx
  ON machine_research_cards (tenant_id, video_id, roster_index);

ALTER TABLE machine_research_cards ENABLE ROW LEVEL SECURITY;
DO $policy$
BEGIN
  CREATE POLICY "Tenant isolation" ON machine_research_cards FOR ALL TO authenticated
    USING (machine_research_cards.tenant_id IN
      (SELECT m.tenant_id FROM memberships AS m WHERE m.user_id = (SELECT auth.uid())))
    WITH CHECK (
      machine_research_cards.tenant_id IN
        (SELECT m.tenant_id FROM memberships AS m WHERE m.user_id = (SELECT auth.uid()))
      AND EXISTS (
        SELECT 1 FROM videos AS v
        WHERE v.id = machine_research_cards.video_id
          AND v.tenant_id = machine_research_cards.tenant_id
      )
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END
$policy$;

COMMENT ON TABLE machine_research_cards IS
  'Compact per-machine operational research cards; raw research/media remain outside this table.';

COMMIT;
