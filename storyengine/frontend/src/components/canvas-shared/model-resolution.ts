import type { Asset } from "@/lib/api";

/**
 * ONE resolver for "which clip model is this shot actually on right now" —
 * extracted out of ShotCard.tsx (where it lived inline as `effectiveModelId`,
 * ~L99-101) so the Director board's CostDial totals and every ShotCard badge
 * read the exact same precedence. A total computed with a different rule
 * than the badge is a bug, not a design choice (Cost Dial chunk brief, P3).
 *
 * Precedence, once a clip exists: `model_used` (whichever model ACTUALLY
 * generated it) — an existing clip's cost is fixed history, a manual
 * override written after the fact does not retroactively change it until
 * the clip is redone. Before a clip exists: `model_override` (the creator's
 * manual pick) > `routed_model` (the automatic router's recommendation) >
 * `videoDefaultModel` (last-resort fallback).
 *
 * `simulateOverride` lets a caller ask "what would this shot resolve to if
 * its override were X instead" WITHOUT mutating anything — CostDial's bulk-
 * action preview (Make all draft/cinematic, Reset to recommended) uses this
 * to price a hypothetical write before it happens, through the identical
 * precedence rule real generation uses. Passing it explicitly as `null`
 * simulates "override cleared" (the Reset action); omitting it (undefined)
 * reads the asset's real stored `model_override`, so every existing caller
 * (ShotCard) that never passes it behaves byte-identical to before this was
 * extracted.
 */
export function resolveEffectiveModel(
  asset: Pick<Asset, "video_clip_url" | "model_used" | "model_override" | "routed_model">,
  videoDefaultModel: string,
  simulateOverride?: string | null,
): string {
  const hasClip = Boolean(asset.video_clip_url);
  if (hasClip) return asset.model_used || videoDefaultModel;
  const override = simulateOverride !== undefined ? simulateOverride : asset.model_override;
  return override || asset.routed_model || videoDefaultModel;
}
