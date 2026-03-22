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
// ---------- Learning Summary ----------

export interface LearningSummary {
  totalSettled: number;
  narrativeSummary: string;
  topPatterns: Array<{
    pattern: string;
    verdict: "KEEP" | "DISCARD" | "NEUTRAL";
    sampleSize: number;
    winRate: number;
  }>;
  bestCategory: { name: string; winRate: number } | null;
  worstCategory: { name: string; winRate: number } | null;
  bestPriceRange: { range: string; winRate: number } | null;
  confidenceCalibration: { avgOnWins: number; avgOnLosses: number };
  activeHypotheses: string[];
}

interface SettledExperiment {
  category: string;
  result: string | null;
  entryPrice: number;
  confidence: number;
  pnl: number | null;
  title: string;
}

/**
 * Generate a narrative learning summary from settled experiments.
 * Pure function — no I/O.
 */
export function generateLearningSummary(
  experiments: SettledExperiment[]
): LearningSummary {
  const settled = experiments.filter((e) => e.result === "won" || e.result === "lost");

  if (settled.length === 0) {
    return {
      totalSettled: 0,
      narrativeSummary: "No settled bets yet. Run cycles and monitor positions to start building your learning base.",
      topPatterns: [],
      bestCategory: null,
      worstCategory: null,
      bestPriceRange: null,
      confidenceCalibration: { avgOnWins: 0, avgOnLosses: 0 },
      activeHypotheses: ["All categories are untested — need 3+ settled bets per category to form patterns."],
    };
  }

  const wins = settled.filter((e) => e.result === "won");
  const losses = settled.filter((e) => e.result === "lost");
  const winRate = Math.round((wins.length / settled.length) * 100);

  // Category analysis
  const catStats: Record<string, { wins: number; total: number }> = {};
  for (const e of settled) {
    catStats[e.category] = catStats[e.category] ?? { wins: 0, total: 0 };
    catStats[e.category].total++;
    if (e.result === "won") catStats[e.category].wins++;
  }

  const catEntries = Object.entries(catStats)
    .filter(([, s]) => s.total >= 3)
    .map(([cat, s]) => ({ name: cat, winRate: Math.round((s.wins / s.total) * 100), total: s.total }))
    .sort((a, b) => b.winRate - a.winRate);

  const bestCategory = catEntries.length > 0 ? catEntries[0] : null;
  const worstCategory = catEntries.length > 1 ? catEntries[catEntries.length - 1] : null;

  const activeHypotheses = Object.entries(catStats)
    .filter(([, s]) => s.total < 3)
    .map(([cat, s]) => `${cat}: ${s.total}/3 samples needed`);

  // Price range analysis
  const priceStats: Record<string, { wins: number; total: number }> = {};
  for (const e of settled) {
    const range = e.entryPrice < 20 ? "cheap (<20¢)" : e.entryPrice <= 50 ? "mid (20-50¢)" : "expensive (>50¢)";
    priceStats[range] = priceStats[range] ?? { wins: 0, total: 0 };
    priceStats[range].total++;
    if (e.result === "won") priceStats[range].wins++;
  }

  const priceEntries = Object.entries(priceStats)
    .map(([range, s]) => ({ range, winRate: Math.round((s.wins / s.total) * 100), total: s.total }))
    .sort((a, b) => b.winRate - a.winRate);

  const bestPriceRange = priceEntries.length > 0 ? priceEntries[0] : null;

  // Confidence calibration
  const avgOnWins = wins.length > 0
    ? Math.round(wins.reduce((sum, e) => sum + e.confidence, 0) / wins.length)
    : 0;
  const avgOnLosses = losses.length > 0
    ? Math.round(losses.reduce((sum, e) => sum + e.confidence, 0) / losses.length)
    : 0;

  // Top patterns
  const topPatterns: LearningSummary["topPatterns"] = [];
  for (const cat of catEntries) {
    topPatterns.push({
      pattern: cat.name,
      verdict: cat.winRate >= 60 ? "KEEP" : cat.winRate <= 40 ? "DISCARD" : "NEUTRAL",
      sampleSize: cat.total,
      winRate: cat.winRate,
    });
  }
  for (const pr of priceEntries) {
    topPatterns.push({
      pattern: pr.range,
      verdict: pr.winRate >= 60 ? "KEEP" : pr.winRate <= 40 ? "DISCARD" : "NEUTRAL",
      sampleSize: pr.total,
      winRate: pr.winRate,
    });
  }

  // Build narrative
  const parts: string[] = [];
  parts.push(`Across ${settled.length} settled bets, overall win rate is ${winRate}%.`);
  if (bestCategory) {
    parts.push(`${bestCategory.name} markets perform best at ${bestCategory.winRate}% (${bestCategory.total} bets).`);
  }
  if (worstCategory && worstCategory.name !== bestCategory?.name) {
    parts.push(`${worstCategory.name} markets are weakest at ${worstCategory.winRate}%.`);
  }
  if (bestPriceRange) {
    parts.push(`${bestPriceRange.range} contracts hit ${bestPriceRange.winRate}% win rate.`);
  }
  if (avgOnWins > 0 && avgOnLosses > 0) {
    const diff = avgOnWins - avgOnLosses;
    if (diff > 5) {
      parts.push(`Confidence scoring is calibrated — wins avg ${avgOnWins} vs losses avg ${avgOnLosses}.`);
    } else {
      parts.push(`Confidence gap is narrow (wins: ${avgOnWins}, losses: ${avgOnLosses}) — scoring needs more data.`);
    }
  }

  return {
    totalSettled: settled.length,
    narrativeSummary: parts.join(" "),
    topPatterns,
    bestCategory,
    worstCategory,
    bestPriceRange,
    confidenceCalibration: { avgOnWins, avgOnLosses },
    activeHypotheses,
  };
}

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
