/**
 * Score Kalshi markets using weighted signals to find best bets.
 * Mirrors: autopilot/core/confidence_scorer.py
 *
 * 5 signals (all normalized 0-100, weighted sum):
 * 1. Price Edge — how far from 50c (stronger conviction = bigger edge)
 * 2. Volume Signal — higher volume = more informed pricing
 * 3. Time to Close — sweet spot 3-14 days
 * 4. Category Fit — historical win rate for this category
 * 5. Price Momentum — recent price movement direction
 */

import type { KalshiMarket } from "../kalshi-types";
import type { BrainConfig } from "./config";

export interface MarketCandidate {
  market: KalshiMarket;
  /** Previous price for momentum calculation (from 24h ago if available) */
  previousPrice?: number;
}

export interface ScoredMarket {
  market: KalshiMarket;
  score: number; // 0-100
  side: "yes" | "no"; // recommended side
  edgeCents: number; // expected edge in cents
  reasoning: string[];
  components: Record<string, number>;
}

/**
 * Score how far the price is from 50c.
 * Markets at 10c or 90c = high conviction, bigger payoff.
 * The further from 50, the more the market has "decided" — but we bet
 * on the side the market hasn't fully priced in yet.
 */
function scorePriceEdge(market: KalshiMarket): { score: number; side: "yes" | "no"; reasoning: string } {
  const yesPrice = market.yes_bid || market.last_price;
  const noPrice = market.no_bid || (100 - yesPrice);

  // Distance from 50c (higher = stronger conviction)
  const distance = Math.abs(yesPrice - 50);

  // Bet on the cheaper side (higher expected value if we're right)
  const side: "yes" | "no" = yesPrice <= 50 ? "yes" : "no";
  const entryPrice = side === "yes" ? yesPrice : noPrice;

  // Score: cheaper contracts = higher edge potential
  // 5c entry → 100 score (huge payoff if right)
  // 50c entry → 0 score (coin flip, no edge)
  const score = Math.max(0, Math.min(100, ((50 - entryPrice) / 50) * 100));

  return {
    score,
    side,
    reasoning: `${side.toUpperCase()} @ ${entryPrice}c (${distance}c from 50) → ${score.toFixed(0)}/100`,
  };
}

/**
 * Score based on 24h trading volume.
 * Higher volume = more liquid, more informed, but also harder to find edge.
 * Sweet spot: moderate volume (some interest, not fully efficient).
 */
function scoreVolume(market: KalshiMarket): { score: number; reasoning: string } {
  const vol = market.volume_24h;

  if (vol <= 0) return { score: 10, reasoning: `Vol 0 → 10/100 (no activity)` };

  // Bell curve: peak at ~500 volume, falloff on both sides
  // Too low (<50) = illiquid, hard to exit
  // Too high (>5000) = fully efficient, no edge
  let score: number;
  if (vol < 50) {
    score = (vol / 50) * 40; // 0-40 for low volume
  } else if (vol <= 2000) {
    score = 40 + ((vol - 50) / 1950) * 60; // 40-100 for sweet spot
  } else {
    score = Math.max(30, 100 - ((vol - 2000) / 8000) * 70); // decay for very high
  }

  score = Math.min(100, Math.max(0, score));
  return { score, reasoning: `Vol ${vol} → ${score.toFixed(0)}/100` };
}

/**
 * Score based on time until market closes.
 * Sweet spot: 3-14 days. Too soon = price locked in. Too far = capital locked.
 */
function scoreTimeToClose(market: KalshiMarket): { score: number; reasoning: string } {
  const closeDate = new Date(market.close_time);
  const now = new Date();
  const daysUntilClose = (closeDate.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);

  if (daysUntilClose <= 0) return { score: 0, reasoning: `Closed → 0/100` };
  if (daysUntilClose < 1) return { score: 20, reasoning: `<1 day → 20/100 (too late)` };

  let score: number;
  if (daysUntilClose < 3) {
    score = 20 + ((daysUntilClose - 1) / 2) * 40; // ramp up 20-60
  } else if (daysUntilClose <= 14) {
    score = 60 + ((daysUntilClose - 3) / 11) * 40; // sweet spot 60-100
  } else if (daysUntilClose <= 30) {
    score = 100 - ((daysUntilClose - 14) / 16) * 40; // decay 100-60
  } else {
    score = Math.max(20, 60 - ((daysUntilClose - 30) / 60) * 40); // slow decay
  }

  score = Math.min(100, Math.max(0, score));
  return { score, reasoning: `${daysUntilClose.toFixed(1)} days → ${score.toFixed(0)}/100` };
}

/**
 * Score based on category historical performance.
 * Reads from config (initially all 50, updated by learning loop).
 */
function scoreCategoryFit(
  market: KalshiMarket,
  categoryScores: Record<string, number>
): { score: number; reasoning: string } {
  const category = market.category || "Unknown";
  const score = categoryScores[category] ?? 50; // neutral if unknown
  return { score, reasoning: `${category} → ${score}/100` };
}

/**
 * Score based on recent price momentum.
 * If price is moving toward our recommended side = confirmation.
 */
function scoreMomentum(
  market: KalshiMarket,
  side: "yes" | "no",
  previousPrice?: number
): { score: number; reasoning: string } {
  if (previousPrice === undefined) {
    return { score: 50, reasoning: `No momentum data → 50/100` };
  }

  const currentPrice = market.last_price;
  const delta = currentPrice - previousPrice;

  // If we're betting YES and price is going up = momentum confirmation
  // If we're betting NO and price is going down = momentum confirmation
  const favorable = (side === "yes" && delta > 0) || (side === "no" && delta < 0);
  const magnitude = Math.abs(delta);

  let score: number;
  if (favorable) {
    score = 50 + Math.min(50, magnitude * 5); // +5 per cent of favorable movement
  } else {
    score = 50 - Math.min(40, magnitude * 4); // -4 per cent of adverse movement
  }

  score = Math.min(100, Math.max(0, score));
  const dir = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  return { score, reasoning: `${dir} ${Math.abs(delta)}c (${favorable ? "favorable" : "adverse"}) → ${score.toFixed(0)}/100` };
}

export function scoreMarket(candidate: MarketCandidate, config: BrainConfig): ScoredMarket {
  const { market, previousPrice } = candidate;

  // 1. Price edge (also determines recommended side)
  const priceResult = scorePriceEdge(market);
  const side = priceResult.side;

  // 2. Volume
  const volumeResult = scoreVolume(market);

  // 3. Time to close
  const timeResult = scoreTimeToClose(market);

  // 4. Category fit
  const categoryResult = scoreCategoryFit(market, config.category_scores);

  // 5. Momentum
  const momentumResult = scoreMomentum(market, side, previousPrice);

  // Weighted sum
  const components: Record<string, number> = {
    price_edge: priceResult.score,
    volume_signal: volumeResult.score,
    time_to_close: timeResult.score,
    category_fit: categoryResult.score,
    price_momentum: momentumResult.score,
  };

  const score =
    priceResult.score * config.weights.price_edge +
    volumeResult.score * config.weights.volume_signal +
    timeResult.score * config.weights.time_to_close +
    categoryResult.score * config.weights.category_fit +
    momentumResult.score * config.weights.price_momentum;

  // Calculate expected edge in cents
  const entryPrice = side === "yes" ? (market.yes_ask || market.last_price) : (market.no_ask || (100 - market.last_price));
  const edgeCents = 100 - entryPrice - 50; // simplified: how much better than coin flip

  const reasoning = [
    `Price: ${priceResult.reasoning}`,
    `Volume: ${volumeResult.reasoning}`,
    `Time: ${timeResult.reasoning}`,
    `Category: ${categoryResult.reasoning}`,
    `Momentum: ${momentumResult.reasoning}`,
  ];

  return { market, score, side, edgeCents, reasoning, components };
}

export function rankMarkets(
  candidates: MarketCandidate[],
  config: BrainConfig
): ScoredMarket[] {
  const scored = candidates.map((c) => scoreMarket(c, config));

  return scored
    .filter((s) => s.score >= config.thresholds.min_confidence)
    .filter((s) => s.edgeCents >= config.thresholds.min_edge_cents)
    .sort((a, b) => b.score - a.score);
}

export function getBestMarket(
  candidates: MarketCandidate[],
  config: BrainConfig
): ScoredMarket | null {
  const ranked = rankMarkets(candidates, config);
  return ranked.length > 0 ? ranked[0] : null;
}
