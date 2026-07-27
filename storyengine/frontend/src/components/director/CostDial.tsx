"use client";

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Gauge, Zap, Gem, RotateCcw } from "lucide-react";
import { bulkUpdateAssetModelOverride, type Asset, type VideoModelInfo } from "@/lib/api";
import { resolveEffectiveModel } from "@/components/canvas-shared/model-resolution";
import { formatCost } from "@/lib/utils";
import { useConfirm } from "@/components/ui/confirm";
import { useToast } from "@/components/ui/toast";

/**
 * The Cost Dial — the scaling story on screen. Three live totals for this
 * video's shots ("All draft" / current assignment / "All cinematic"), plus
 * three bulk actions that only ever touch `assets.model_override` (routing
 * for the NEXT clip generation, never a spend). Mounted above the scene list
 * in SceneAltitudeView.tsx.
 *
 * Every number here reuses `resolveEffectiveModel` (canvas-shared/model-
 * resolution.ts) — the SAME precedence rule ShotCard's own badge uses — so
 * this dial and every shot's badge can never disagree (Cost Dial chunk
 * brief, P3). Cheapest/premium models are derived at runtime from the wired
 * model list's own `tier` + `cost_per_clip` fields (never a hardcoded model
 * id), mirroring exactly what actions._draft_tier_model_id() /
 * _premium_reference_price() do server-side (checklist §1.2/C15).
 *
 * Prices are cheapest-duration-tier estimates, same imprecision the rest of
 * the app already quotes (docs/cost-awareness.md) — every total here is
 * labeled "~" or "estimate", never presented as exact billing.
 */
export function CostDial({
  videoId,
  assets,
  models,
  videoDefaultModel,
  priceForModel,
  modelDisplayName,
}: {
  videoId: string;
  assets: Asset[];
  models: VideoModelInfo[];
  videoDefaultModel: string;
  priceForModel: (id: string | null | undefined) => number;
  modelDisplayName: (id: string | null | undefined) => string;
}) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  const totalShots = assets.length;

  const wiredVideoModels = useMemo(
    () => (models ?? []).filter((m) => m.kind === "video" && m.wired && m.cost_per_clip != null),
    [models],
  );

  // Cheapest wired model, preferring the registry's own "draft" tier tag —
  // same rule actions._draft_tier_model_id() applies server-side. Falls back
  // to the cheapest wired model of ANY tier if the registry ever ships with
  // no draft-tagged entry, so this row never just disappears.
  const cheapestModel = useMemo(() => {
    if (!wiredVideoModels.length) return null;
    const draftTier = wiredVideoModels.filter((m) => m.tier === "draft");
    const pool = draftTier.length ? draftTier : wiredVideoModels;
    return pool.reduce((best, m) => ((m.cost_per_clip ?? Infinity) < (best.cost_per_clip ?? Infinity) ? m : best));
  }, [wiredVideoModels]);

  // Cheapest wired PREMIUM-tier model — same rule
  // actions._premium_reference_price() applies. Genuinely null when no
  // premium-tier model is wired yet; the "All cinematic" row and its bulk
  // action are disabled rather than guessing a stand-in model.
  const premiumModel = useMemo(() => {
    const premiumTier = wiredVideoModels.filter((m) => m.tier === "premium");
    if (!premiumTier.length) return null;
    return premiumTier.reduce((best, m) => ((m.cost_per_clip ?? Infinity) < (best.cost_per_clip ?? Infinity) ? m : best));
  }, [wiredVideoModels]);

  // "Current" — the real, live assignment. hasClip-aware (resolveEffectiveModel
  // with no simulated override): a shot that's already been clipped prices at
  // its real historical model_used, matching ShotCard's own badge exactly
  // (Cost Dial chunk brief, P3 — a total that disagrees with the badge is a
  // bug). Sum of every shot's price if `simulateOverride` were applied
  // instead of its real stored override.
  const totalWith = (simulateOverride: string | null | undefined) =>
    assets.reduce((sum, a) => sum + priceForModel(resolveEffectiveModel(a, videoDefaultModel, simulateOverride)), 0);

  const currentTotal = useMemo(
    () => totalWith(undefined),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [assets, videoDefaultModel, priceForModel],
  );
  // "All draft" / "All cinematic" — the literal, unconditional hypothetical
  // the requirement asks for ("every shot on the cheapest/premium model"),
  // so this is a FLAT totalShots x price, deliberately NOT gated on hasClip.
  // A hasClip-aware version (matching "Current"'s formula) would silently
  // collapse to the current total for any video whose shots already have
  // clips — every clip keeps its real historical cost until it's redone,
  // which is exactly correct for "Current" but would make these two rows
  // inert (unable to show the scaling story at all) once a video has any
  // clips. That's the wrong trade for a row whose entire point is "what
  // would the WHOLE video cost on this model" — found by testing against a
  // real 32-shot video where every shot already has a clip.
  const draftTotal = useMemo(
    () => (cheapestModel ? totalShots * (cheapestModel.cost_per_clip ?? 0) : null),
    [totalShots, cheapestModel],
  );
  const cinematicTotal = useMemo(
    () => (premiumModel ? totalShots * (premiumModel.cost_per_clip ?? 0) : null),
    [totalShots, premiumModel],
  );
  // "Reset to recommended" only ever clears `model_override` — a genuinely
  // hasClip-gated preview (unlike the two above) is the HONEST number here,
  // since the write itself can never touch an already-clipped row's real
  // cost; only not-yet-clipped rows' future routing changes.
  const resetTotal = useMemo(
    () => totalWith(null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [assets, videoDefaultModel, priceForModel],
  );

  // Current row's per-model breakdown — "10 x Veo 3.1 Quality, 140 x Grok
  // Imagine" instead of a flat count, since this is the one row where the
  // real assignment is genuinely mixed. Sorted priciest-first.
  const currentGroups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const a of assets) {
      const id = resolveEffectiveModel(a, videoDefaultModel);
      counts.set(id, (counts.get(id) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .map(([id, count]) => ({ id, count, price: priceForModel(id) }))
      .sort((a, b) => b.price - a.price);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assets, videoDefaultModel, priceForModel]);

  const currentBreakdown = currentGroups
    .map((g) => `${g.count} × ${modelDisplayName(g.id) || g.id}`)
    .join(" · ");

  const runBulk = async (opts: {
    label: string;
    targetOverride: string | null;
    targetTotal: number | null;
    changedCount: number;
    /** true for "Make all draft"/"Make all cinematic" (targetTotal is the
     * flat, unconditional "every shot on this model" hypothetical — it does
     * NOT reconcile 1:1 with currentTotal when some shots already have a
     * clip). false for "Reset to recommended" (targetTotal IS a real,
     * hasClip-aware post-write total, safe to frame as a plain X -> Y
     * move). Only changes the confirm copy, never the math. */
    isHypothetical: boolean;
  }) => {
    if (opts.targetTotal == null) return;
    if (opts.changedCount === 0) {
      toast.info(`Every shot is already set to ${opts.label}. Nothing to change.`);
      return;
    }
    const restNote = opts.changedCount < totalShots ? " (the rest are already there)" : "";
    const routingLine =
      `This sets ${opts.changedCount} of ${totalShots} shot${totalShots === 1 ? "" : "s"} to ${opts.label} ` +
      `for their next clip${restNote}. Shots that already have a clip keep their real cost until that clip is redone.`;
    const costLine = opts.isHypothetical
      ? `If every shot on this video were generated fresh on ${opts.label}, the full video would cost about ` +
        `${formatCost(opts.targetTotal)} — today's real total is about ${formatCost(currentTotal)}.`
      : `Estimated full-video cost: ${formatCost(currentTotal)} → ${formatCost(opts.targetTotal)}.`;
    const ok = await confirm({
      title: opts.label,
      message:
        `${routingLine}\n\n${costLine}\n\n` +
        `This is free — it only changes routing for future generation. Nothing renders and nothing is billed.`,
      confirmLabel: `Set ${opts.changedCount} shot${opts.changedCount === 1 ? "" : "s"}`,
    });
    if (!ok) return;
    setBusy(opts.label);
    try {
      const res = await bulkUpdateAssetModelOverride(videoId, opts.targetOverride);
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-actions", videoId] });
      toast.success(`${res.updated} shot${res.updated === 1 ? "" : "s"} updated.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't update the shots.");
    } finally {
      setBusy(null);
    }
  };

  const draftChangedCount = cheapestModel
    ? assets.filter((a) => (a.model_override ?? null) !== cheapestModel.id).length
    : 0;
  const cinematicChangedCount = premiumModel
    ? assets.filter((a) => (a.model_override ?? null) !== premiumModel.id).length
    : 0;
  const resetChangedCount = assets.filter((a) => a.model_override != null).length;

  if (totalShots === 0) return null;

  return (
    <div className="flex flex-none flex-col gap-2.5 border-b border-line-soft bg-surface px-5 py-3.5">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <DialTile
          icon={<Zap size={13} />}
          accent="var(--text-secondary, #9AA5B1)"
          label="All draft"
          sub={cheapestModel ? modelDisplayName(cheapestModel.id) : "No wired model"}
          total={draftTotal}
          count={`${totalShots} shot${totalShots === 1 ? "" : "s"}`}
        />
        <DialTile
          icon={<Gauge size={13} />}
          accent="var(--turquoise)"
          label="Current"
          sub="live assignment"
          total={currentTotal}
          count={currentBreakdown || `${totalShots} shot${totalShots === 1 ? "" : "s"}`}
          highlighted
        />
        <DialTile
          icon={<Gem size={13} />}
          accent="var(--purple)"
          label="All cinematic"
          sub={premiumModel ? modelDisplayName(premiumModel.id) : "No premium model wired"}
          total={cinematicTotal}
          count={`${totalShots} shot${totalShots === 1 ? "" : "s"}`}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10.5px] font-medium uppercase tracking-[0.08em] text-faint">
          Free — routing only, nothing generates
        </span>
        <div className="ml-auto flex flex-wrap gap-1.5">
          <button
            type="button"
            disabled={!cheapestModel || busy !== null}
            onClick={() =>
              cheapestModel &&
              runBulk({
                label: `all draft (${modelDisplayName(cheapestModel.id)})`,
                targetOverride: cheapestModel.id,
                targetTotal: draftTotal,
                changedCount: draftChangedCount,
                isHypothetical: true,
              })
            }
            title={cheapestModel ? undefined : "No wired video model available"}
            className="h-7 rounded-[8px] border border-line-soft bg-deep px-2.5 text-[11.5px] font-medium text-dim transition-colors hover:border-turquoise/40 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy?.startsWith("all draft") ? "Setting…" : "Make all draft"}
          </button>
          <button
            type="button"
            disabled={!premiumModel || busy !== null}
            onClick={() =>
              premiumModel &&
              runBulk({
                label: `all cinematic (${modelDisplayName(premiumModel.id)})`,
                targetOverride: premiumModel.id,
                targetTotal: cinematicTotal,
                changedCount: cinematicChangedCount,
                isHypothetical: true,
              })
            }
            title={premiumModel ? undefined : "No wired premium-tier model yet"}
            className="h-7 rounded-[8px] border border-purple/35 bg-purple/[0.08] px-2.5 text-[11.5px] font-medium text-purple transition-colors hover:border-purple/60 hover:bg-purple/[0.15] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy?.startsWith("all cinematic") ? "Setting…" : "Make all cinematic"}
          </button>
          <button
            type="button"
            disabled={resetChangedCount === 0 || busy !== null}
            onClick={() =>
              runBulk({
                label: "the recommendation",
                targetOverride: null,
                targetTotal: resetTotal,
                changedCount: resetChangedCount,
                isHypothetical: false,
              })
            }
            title={resetChangedCount === 0 ? "Every shot is already on the recommendation" : undefined}
            className="flex h-7 items-center gap-1 rounded-[8px] border border-line-soft bg-deep px-2.5 text-[11.5px] font-medium text-dim transition-colors hover:border-turquoise/40 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
          >
            <RotateCcw size={11} />
            {busy === "the recommendation" ? "Resetting…" : "Reset to recommended"}
          </button>
        </div>
      </div>
    </div>
  );
}

function DialTile({
  icon,
  accent,
  label,
  sub,
  total,
  count,
  highlighted,
}: {
  icon: React.ReactNode;
  accent: string;
  label: string;
  sub: string;
  total: number | null;
  count: string;
  highlighted?: boolean;
}) {
  return (
    <div
      className="flex flex-col gap-0.5 rounded-card-sm border px-3 py-2"
      style={{
        borderColor: highlighted ? "rgba(0,212,170,0.3)" : "var(--line-soft)",
        background: highlighted ? "rgba(0,212,170,0.06)" : "var(--bg-deep)",
      }}
    >
      <span className="inline-flex items-center gap-1 text-[10.5px] font-semibold uppercase tracking-[0.06em]" style={{ color: accent }}>
        {icon} {label}
      </span>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[17px] font-bold tabular-nums text-ink">
          {total == null ? "—" : `~${formatCost(total)}`}
        </span>
      </div>
      <div className="truncate text-[10.5px] text-dim" title={count}>
        {count}
      </div>
      <div className="truncate text-[9.5px] text-faint" title={sub}>
        {sub}
      </div>
    </div>
  );
}
