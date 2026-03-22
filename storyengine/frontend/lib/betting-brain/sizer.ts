/**
 * Position sizing using simplified Kelly Criterion.
 * Mirrors: No direct autopilot equivalent — new module.
 *
 * Half-Kelly: conservative sizing to reduce variance.
 * Max 15% of bankroll per bet. Min $1.
 */

import type { BrainConfig } from "./config";
import type { ScoredMarket } from "./scorer";

export interface PositionSize {
  contracts: number;
  totalCostCents: number;
  pctOfBankroll: number;
  reasoning: string;
}

/**
 * Calculate position size using half-Kelly criterion.
 *
 * Kelly formula: f* = (bp - q) / b
 * Where:
 *   b = odds (payout ratio: if we bet 20c, we win 80c, so b = 80/20 = 4)
 *   p = estimated probability of winning (from confidence score)
 *   q = 1 - p
 *   f* = fraction of bankroll to bet
 *
 * We use HALF-Kelly (f divided by 2) for safety.
 */
export function calculateSize(
  scored: ScoredMarket,
  bankrollCents: number,
  config: BrainConfig
): PositionSize {
  const entryPrice =
    scored.side === "yes"
      ? scored.market.yes_ask || scored.market.last_price
      : scored.market.no_ask || 100 - scored.market.last_price;

  // Clamp entry price to reasonable range
  const price = Math.max(1, Math.min(99, entryPrice));

  // Odds: payout per dollar risked
  // If we buy YES at 20c, we get 100c if right → net gain 80c → odds = 80/20 = 4
  const payoutIfWin = 100 - price; // cents gained per contract
  const odds = payoutIfWin / price;

  // Estimated win probability from confidence score
  // Score 60 = 55% chance, Score 80 = 65% chance, Score 100 = 75% chance
  // Conservative mapping: don't assume >75% even at max confidence
  const winProb = 0.45 + (scored.score / 100) * 0.30; // 45-75%
  const loseProb = 1 - winProb;

  // Kelly fraction
  const kelly = (odds * winProb - loseProb) / odds;

  // Half-Kelly for safety
  const halfKelly = Math.max(0, kelly / 2);

  // Apply bankroll limits
  const maxBetCents = bankrollCents * config.thresholds.max_bet_pct;
  const betCents = Math.min(halfKelly * bankrollCents, maxBetCents);
  const finalBetCents = Math.max(betCents, config.thresholds.min_bet_cents);

  // Don't bet more than we have
  const clampedBet = Math.min(finalBetCents, bankrollCents * 0.95); // keep 5% reserve

  // Convert to contracts
  const contracts = Math.max(1, Math.floor(clampedBet / price));
  const totalCost = contracts * price;
  const pctOfBankroll = totalCost / bankrollCents;

  const reasoning =
    `Entry ${price}c, odds ${odds.toFixed(1)}:1, ` +
    `est. win ${(winProb * 100).toFixed(0)}%, ` +
    `Kelly ${(kelly * 100).toFixed(1)}% → half ${(halfKelly * 100).toFixed(1)}% → ` +
    `${contracts} contracts @ ${price}c = $${(totalCost / 100).toFixed(2)} ` +
    `(${(pctOfBankroll * 100).toFixed(1)}% of bankroll)`;

  return { contracts, totalCostCents: totalCost, pctOfBankroll, reasoning };
}
