/**
 * Extract patterns from settled bets and update memory files.
 * Mirrors: autopilot/learning/learning_extractor.py + memory_writer.py
 *
 * After each bet settles, extract:
 * - Category performance (geopolitics wins more than economy?)
 * - Price range patterns (cheap bets win more?)
 * - Timing patterns (3-14 day markets better?)
 * - Volume patterns (high/low volume edge?)
 */

import { readFileSync, writeFileSync, existsSync } from "fs";
import { join } from "path";
import type { SettledBet } from "./state";

export interface ExtractedLearning {
  category: "category" | "price_range" | "timing" | "volume" | "general";
  pattern: string;
  verdict: "KEEP" | "DISCARD" | "NEUTRAL";
  confidence: number;
  detail: string;
}

const MEMORY_DIR = join(__dirname, "memory");

function readMemoryFile(filename: string): string {
  const path = join(MEMORY_DIR, filename);
  if (!existsSync(path)) return "";
  return readFileSync(path, "utf-8");
}

function appendToMemoryFile(filename: string, content: string): void {
  const path = join(MEMORY_DIR, filename);
  const existing = existsSync(path) ? readFileSync(path, "utf-8") : "";
  writeFileSync(path, existing + "\n" + content);
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
 * Extract all learnings from a settled bet.
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
 * Write learnings to memory files.
 */
export function writeLearnings(bet: SettledBet, learnings: ExtractedLearning[]): void {
  const date = new Date().toISOString().split("T")[0];
  const pnlStr = `${bet.pnl > 0 ? "+" : ""}$${(bet.pnl / 100).toFixed(2)}`;

  // 1. Append to experiments log
  const experimentEntry = `
## Bet: "${bet.title}"
- Date: ${date}
- Side: ${bet.side.toUpperCase()} @ ${bet.entryPrice}c
- Contracts: ${bet.contracts}
- Cost: $${(bet.totalCost / 100).toFixed(2)}
- Result: ${bet.result.toUpperCase()} (${pnlStr})
- Confidence: ${bet.confidence.toFixed(0)}/100
- Category: ${bet.category}
- Learnings: ${learnings.map((l) => l.detail).join("; ")}
`;
  appendToMemoryFile("experiments_log.md", experimentEntry);

  // 2. Update category performance
  const catLearnings = learnings.filter((l) => l.category === "category");
  if (catLearnings.length > 0) {
    const entries = catLearnings.map((l) => `- ${l.detail} (${l.verdict})`).join("\n");
    appendToMemoryFile("category_performance.md", `\n${entries}`);
  }

  // 3. Update market patterns
  const priceLearnings = learnings.filter((l) => l.category === "price_range");
  if (priceLearnings.length > 0) {
    const entries = priceLearnings.map((l) => `- ${l.detail} (${l.verdict})`).join("\n");
    appendToMemoryFile("market_patterns.md", `\n${entries}`);
  }

  // 4. Update timing patterns
  const timingLearnings = learnings.filter((l) => l.category === "timing");
  if (timingLearnings.length > 0) {
    const entries = timingLearnings.map((l) => `- ${l.detail} (${l.verdict})`).join("\n");
    appendToMemoryFile("timing_patterns.md", `\n${entries}`);
  }
}

/**
 * Read aggregated learnings from memory to inform scoring.
 * Returns category win rates for the scorer's category_fit signal.
 */
export function getCategoryWinRates(): Record<string, number> {
  const content = readMemoryFile("category_performance.md");
  if (!content) return {};

  const rates: Record<string, { wins: number; total: number }> = {};

  for (const line of content.split("\n")) {
    const keepMatch = line.match(/^- (.+?): won .+ \(KEEP\)/);
    const discardMatch = line.match(/^- (.+?): lost .+ \(DISCARD\)/);

    if (keepMatch) {
      const cat = keepMatch[1];
      rates[cat] = rates[cat] ?? { wins: 0, total: 0 };
      rates[cat].wins++;
      rates[cat].total++;
    } else if (discardMatch) {
      const cat = discardMatch[1];
      rates[cat] = rates[cat] ?? { wins: 0, total: 0 };
      rates[cat].total++;
    }
  }

  // Convert to 0-100 scores
  const scores: Record<string, number> = {};
  for (const [cat, data] of Object.entries(rates)) {
    if (data.total >= 3) {
      // Need 3+ samples to move from default 50
      scores[cat] = Math.round((data.wins / data.total) * 100);
    }
  }

  return scores;
}
