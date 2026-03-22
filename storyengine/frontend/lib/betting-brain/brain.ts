/**
 * Betting Brain — Main Orchestrator
 * Mirrors: autopilot/autopilot.py
 *
 * The loop: ANALYZE → SIZE → BET → MONITOR → LEARN → REPEAT
 *
 * Paper trading mode: simulates bets against real market data.
 * Live mode: places real orders via Kalshi API.
 */

import type { KalshiMarket } from "../kalshi-types";
import type { BrainConfig } from "./config";
import {
  type BrainState,
  type ActiveBet,
  loadState,
  saveState,
  recordBet,
  settleBet,
  canPlaceBet,
  getWinRate,
} from "./state";
import { type ScoredMarket, type MarketCandidate, rankMarkets, getBestMarket } from "./scorer";
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

export interface MonitorResult {
  settled: Array<{
    betId: string;
    ticker: string;
    result: "won" | "lost" | "push";
    pnl: number;
  }>;
  active: Array<{
    betId: string;
    ticker: string;
    currentPrice: number;
    unrealizedPnl: number;
  }>;
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

// ---------- Core Functions ----------

/**
 * Run one brain cycle: score markets → pick best → size → place bet.
 */
export function runCycle(
  markets: KalshiMarket[],
  config: BrainConfig,
  state?: BrainState
): CycleResult {
  const currentState = state ?? loadState();

  // 1. Check if enabled
  if (!currentState.enabled) {
    return { action: "disabled", reason: "Brain is disabled", state: currentState };
  }

  // 2. Check if we can place a bet
  const canBet = canPlaceBet(currentState, config.thresholds);
  if (!canBet.allowed) {
    return { action: "not_ready", reason: canBet.reason!, state: currentState };
  }

  // 3. Filter to open markets only
  const openMarkets = markets.filter((m) => m.status === "open");
  if (openMarkets.length === 0) {
    return { action: "no_bet", reason: "No open markets available", state: currentState };
  }

  // 4. Score all markets
  const candidates: MarketCandidate[] = openMarkets.map((market) => ({ market }));
  const rankings = rankMarkets(candidates, config);

  if (rankings.length === 0) {
    return {
      action: "no_bet",
      reason: `No markets meet confidence threshold (${config.thresholds.min_confidence})`,
      rankings: [],
      state: currentState,
    };
  }

  // 5. Pick best market (skip markets we already have positions in)
  const activeTickerSet = new Set(currentState.active_bets.map((b) => b.ticker));
  const best = rankings.find((r) => !activeTickerSet.has(r.market.ticker));

  if (!best) {
    return {
      action: "no_bet",
      reason: "All qualifying markets already have active positions",
      rankings,
      state: currentState,
    };
  }

  // 6. Size the position
  const size = calculateSize(best, currentState.bankroll_cents, config);

  // 7. Create the bet record
  const bet: ActiveBet = {
    id: `bet_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    ticker: best.market.ticker,
    title: best.market.title,
    side: best.side,
    contracts: size.contracts,
    entryPrice: best.side === "yes"
      ? (best.market.yes_ask || best.market.last_price)
      : (best.market.no_ask || 100 - best.market.last_price),
    totalCost: size.totalCostCents,
    placedAt: new Date().toISOString(),
    confidence: best.score,
    reasoning: [...best.reasoning, `Size: ${size.reasoning}`],
    category: best.market.category,
    closeTime: best.market.close_time,
  };

  // 8. Update state (paper mode: just record locally)
  const newState = recordBet(currentState, bet);
  saveState(newState);

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
 * Check active bets against current market data. Settle any resolved markets.
 */
export function monitorPositions(
  markets: KalshiMarket[],
  state?: BrainState
): MonitorResult {
  let currentState = state ?? loadState();
  const marketMap = new Map(markets.map((m) => [m.ticker, m]));

  const settled: MonitorResult["settled"] = [];
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

      const payout = won ? bet.contracts * 100 : 0; // 100c per contract if won, 0 if lost
      const result = won ? "won" : "lost";
      const pnl = payout - bet.totalCost;

      const learnings = [
        `${result.toUpperCase()}: ${bet.side} @ ${bet.entryPrice}c on "${bet.title}"`,
        `Category: ${bet.category}`,
        `Confidence was: ${bet.confidence.toFixed(0)}`,
        `P&L: ${pnl > 0 ? "+" : ""}${(pnl / 100).toFixed(2)}`,
      ];

      currentState = settleBet(currentState, bet.id, result, payout, learnings);
      settled.push({ betId: bet.id, ticker: bet.ticker, result, pnl });
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

  if (settled.length > 0) {
    saveState(currentState);
  }

  return { settled, active };
}

/**
 * Get current brain status summary.
 */
export function getStatus(config: BrainConfig, state?: BrainState): BrainStatus {
  const s = state ?? loadState();
  return {
    enabled: s.enabled,
    mode: s.mode,
    bankroll: s.bankroll_cents / 100,
    startingBankroll: s.starting_bankroll_cents / 100,
    totalPnl: s.total_pnl_cents / 100,
    winRate: getWinRate(s),
    totalBets: s.total_bets,
    activeBets: s.active_bets.length,
    maxPositions: config.thresholds.max_positions,
    lastCycle: s.last_cycle,
    lastBet: s.last_bet,
  };
}

/**
 * Force-run a cycle (ignore cooldown).
 */
export function forceCycle(
  markets: KalshiMarket[],
  config: BrainConfig
): CycleResult {
  const state = loadState();

  // Override cooldown by clearing last_bet
  const overriddenState = { ...state, last_bet: null };
  return runCycle(markets, config, overriddenState);
}

/**
 * Toggle brain on/off.
 */
export function toggleBrain(enabled: boolean): BrainState {
  const state = loadState();
  state.enabled = enabled;
  saveState(state);
  return state;
}
