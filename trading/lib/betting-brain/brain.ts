/**
 * Betting Brain — Main Orchestrator (Pure Functions)
 * Mirrors: autopilot/autopilot.py
 *
 * The loop: ANALYZE → SIZE → BET → MONITOR → LEARN → REPEAT
 *
 * All functions are PURE — take state in, return new state out.
 * No filesystem I/O. Prisma persistence handled by API route.
 */

import type { KalshiMarket } from "../kalshi-types";
import type { BrainConfig } from "./config";
import {
  type BrainState,
  type ActiveBet,
  type SettledBet,
  recordBet,
  settleBet,
  canPlaceBet,
  getWinRate,
} from "./state";
import { type ScoredMarket, type MarketCandidate, rankMarkets } from "./scorer";
import { calculateSize } from "./sizer";

// ---------- Types ----------

export interface CycleResult {
  action: "bet_placed" | "no_bet" | "not_ready" | "disabled" | "error";
  reason: string;
  bet?: ActiveBet;
  scored?: ScoredMarket;
  rankings?: ScoredMarket[];
  state: BrainState;
}

export interface SettlementResult {
  betId: string;
  ticker: string;
  result: "won" | "lost" | "push";
  pnl: number;
  settled: SettledBet;
}

export interface MonitorResult {
  settlements: SettlementResult[];
  active: Array<{
    betId: string;
    ticker: string;
    currentPrice: number;
    unrealizedPnl: number;
  }>;
  state: BrainState;
}

export interface BrainStatus {
  enabled: boolean;
  mode: "paper" | "live";
  bankroll: number; // dollars
  startingBankroll: number;
  totalPnl: number; // dollars
  winRate: number;
  totalBets: number;
  activeBets: number;
  maxPositions: number;
  lastCycle: string | null;
  lastBet: string | null;
}

// ---------- Core Functions (all pure) ----------

/**
 * Run one brain cycle: score markets → pick best → size → record bet.
 * Returns new state — caller persists.
 */
export function runCycle(
  markets: KalshiMarket[],
  config: BrainConfig,
  state: BrainState
): CycleResult {
  // 1. Check if enabled
  if (!state.enabled) {
    return { action: "disabled", reason: "Brain is disabled", state };
  }

  // 2. Check if we can place a bet
  const canBet = canPlaceBet(state, config.thresholds);
  if (!canBet.allowed) {
    return { action: "not_ready", reason: canBet.reason!, state };
  }

  // 3. Filter to open markets only
  const openMarkets = markets.filter((m) => m.status === "open");
  if (openMarkets.length === 0) {
    return { action: "no_bet", reason: "No open markets available", state };
  }

  // 4. Score all markets
  const candidates: MarketCandidate[] = openMarkets.map((market) => ({ market }));
  const rankings = rankMarkets(candidates, config);

  if (rankings.length === 0) {
    return {
      action: "no_bet",
      reason: `No markets meet confidence threshold (${config.thresholds.min_confidence})`,
      rankings: [],
      state,
    };
  }

  // 5. Pick best market (skip markets we already have positions in)
  const activeTickerSet = new Set(state.active_bets.map((b) => b.ticker));
  const best = rankings.find((r) => !activeTickerSet.has(r.market.ticker));

  if (!best) {
    return {
      action: "no_bet",
      reason: "All qualifying markets already have active positions",
      rankings,
      state,
    };
  }

  // 6. Size the position
  const size = calculateSize(best, state.bankroll_cents, config);

  // 7. Create the bet record
  const bet: ActiveBet = {
    id: `bet_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    ticker: best.market.ticker,
    title: best.market.title,
    side: best.side,
    contracts: size.contracts,
    entryPrice:
      best.side === "yes"
        ? best.market.yes_ask || best.market.last_price
        : best.market.no_ask || 100 - best.market.last_price,
    totalCost: size.totalCostCents,
    placedAt: new Date().toISOString(),
    confidence: best.score,
    reasoning: [...best.reasoning, `Size: ${size.reasoning}`],
    category: best.market.category,
    closeTime: best.market.close_time,
  };

  // 8. Update state (pure — caller persists)
  const newState = recordBet(state, bet);

  return {
    action: "bet_placed",
    reason: `${config.mode.toUpperCase()}: ${best.side.toUpperCase()} on "${best.market.title}" — ${size.contracts} contracts @ ${bet.entryPrice}c (confidence: ${best.score.toFixed(0)})`,
    bet,
    scored: best,
    rankings,
    state: newState,
  };
}

/**
 * Check active bets against current market data. Settle resolved markets.
 * Returns new state + settlements — caller persists.
 */
export function monitorPositions(
  markets: KalshiMarket[],
  state: BrainState
): MonitorResult {
  let currentState = state;
  const marketMap = new Map(markets.map((m) => [m.ticker, m]));

  const settlements: SettlementResult[] = [];
  const active: MonitorResult["active"] = [];

  for (const bet of currentState.active_bets) {
    const market = marketMap.get(bet.ticker);
    if (!market) {
      active.push({ betId: bet.id, ticker: bet.ticker, currentPrice: bet.entryPrice, unrealizedPnl: 0 });
      continue;
    }

    // Check if market has settled
    if (market.status === "settled" && market.result) {
      const won =
        (bet.side === "yes" && (market.result === "yes" || market.result === "all_yes")) ||
        (bet.side === "no" && (market.result === "no" || market.result === "all_no"));

      const payout = won ? bet.contracts * 100 : 0;
      const result = won ? "won" as const : "lost" as const;

      const learnings = [
        `${result.toUpperCase()}: ${bet.side} @ ${bet.entryPrice}c on "${bet.title}"`,
        `Category: ${bet.category}`,
        `Confidence was: ${bet.confidence.toFixed(0)}`,
        `P&L: ${(payout - bet.totalCost) > 0 ? "+" : ""}$${((payout - bet.totalCost) / 100).toFixed(2)}`,
      ];

      const settleResult = settleBet(currentState, bet.id, result, payout, learnings);
      currentState = settleResult.state;

      if (settleResult.settled) {
        settlements.push({
          betId: bet.id,
          ticker: bet.ticker,
          result,
          pnl: payout - bet.totalCost,
          settled: settleResult.settled,
        });
      }
    } else {
      // Still active — calculate unrealized P&L
      const currentPrice =
        bet.side === "yes"
          ? market.yes_bid || market.last_price
          : market.no_bid || 100 - market.last_price;
      const unrealizedPnl = (currentPrice - bet.entryPrice) * bet.contracts;
      active.push({ betId: bet.id, ticker: bet.ticker, currentPrice, unrealizedPnl });
    }
  }

  return { settlements, active, state: currentState };
}

/**
 * Get current brain status summary.
 */
export function getStatus(config: BrainConfig, state: BrainState): BrainStatus {
  return {
    enabled: state.enabled,
    mode: state.mode,
    bankroll: state.bankroll_cents / 100,
    startingBankroll: state.starting_bankroll_cents / 100,
    totalPnl: state.total_pnl_cents / 100,
    winRate: getWinRate(state),
    totalBets: state.total_bets,
    activeBets: state.active_bets.length,
    maxPositions: config.thresholds.max_positions,
    lastCycle: state.last_cycle,
    lastBet: state.last_bet,
  };
}
