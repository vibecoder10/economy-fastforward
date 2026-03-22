/**
 * Extract patterns from settled bets (pure functions).
 * Mirrors: autopilot/learning/learning_extractor.py
 *
 * NO filesystem I/O. Learnings stored in BetExperiment.learnings (Prisma).
 * Category win rates computed from BetExperiment records via SQL.
 */

import type { SettledBet } from "./state";

export interface ExtractedLearning {
  category: "category" | "price_range" | "timing" | "volume" | "general";
  pattern: string;
  verdict: "KEEP" | "DISCARD" | "NEUTRAL";
  confidence: number;
  detail: string;
}

function getVerdict(result: "won" | "lost" | "push"): "KEEP" | "DISCARD" | "NEUTRAL" {
  switch (result) {
    case "won":
      return "KEEP";
    case "lost":
      return "DISCARD";
    case "push":
      return "NEUTRAL";
  }
}

function getPriceRange(price: number): string {
  if (price < 20) return "cheap (<20c)";
  if (price <= 50) return "mid (20-50c)";
  return "expensive (>50c)";
}

function getDaysToClose(placedAt: string, closeTime: string): number {
  const placed = new Date(placedAt);
  const close = new Date(closeTime);
  return (close.getTime() - placed.getTime()) / (1000 * 60 * 60 * 24);
}

/**
 * Extract all learnings from a settled bet. Pure function.
 */
export function extractLearnings(bet: SettledBet): ExtractedLearning[] {
  const learnings: ExtractedLearning[] = [];
  const verdict = getVerdict(bet.result);
  const pnlStr = `${bet.pnl > 0 ? "+" : ""}$${(bet.pnl / 100).toFixed(2)}`;

  // 1. Category learning
  learnings.push({
    category: "category",
    pattern: bet.category,
    verdict,
    confidence: verdict === "KEEP" ? 60 : verdict === "DISCARD" ? 40 : 50,
    detail: `${bet.category}: ${bet.result} ${pnlStr} — "${bet.title}"`,
  });

  // 2. Price range learning
  const priceRange = getPriceRange(bet.entryPrice);
  learnings.push({
    category: "price_range",
    pattern: priceRange,
    verdict,
    confidence: verdict === "KEEP" ? 55 : 45,
    detail: `${priceRange}: ${bet.side} @ ${bet.entryPrice}c → ${bet.result} ${pnlStr}`,
  });

  // 3. Timing learning
  const daysToClose = getDaysToClose(bet.placedAt, bet.closeTime);
  const timeRange =
    daysToClose < 3 ? "short (<3 days)" : daysToClose <= 14 ? "medium (3-14 days)" : "long (>14 days)";
  learnings.push({
    category: "timing",
    pattern: timeRange,
    verdict,
    confidence: verdict === "KEEP" ? 55 : 45,
    detail: `${timeRange} (${daysToClose.toFixed(1)}d): ${bet.result} ${pnlStr}`,
  });

  return learnings;
}

/**
 * Compute category win rates from settled bet experiments.
 * Takes raw DB records, returns category → score (0-100) mapping.
 * Used by scorer's category_fit signal.
 */
export function computeCategoryScores(
  experiments: Array<{ category: string; result: string | null }>
): Record<string, number> {
  const stats: Record<string, { wins: number; total: number }> = {};

  for (const exp of experiments) {
    if (!exp.result || exp.result === "push") continue;
    const cat = exp.category;
    stats[cat] = stats[cat] ?? { wins: 0, total: 0 };
    stats[cat].total++;
    if (exp.result === "won") stats[cat].wins++;
  }

  const scores: Record<string, number> = {};
  for (const [cat, data] of Object.entries(stats)) {
    // Need 3+ samples to move from default 50
    if (data.total >= 3) {
      scores[cat] = Math.round((data.wins / data.total) * 100);
    }
  }

  return scores;
}
