/**
 * Betting brain state types and pure transform functions.
 *
 * NO filesystem I/O. All persistence handled by Prisma in the API route.
 * Mirrors: autopilot/core/state_manager.py
 */

export interface ActiveBet {
  id: string;
  ticker: string;
  title: string;
  side: "yes" | "no";
  contracts: number;
  entryPrice: number; // cents
  totalCost: number; // cents
  placedAt: string; // ISO date
  confidence: number; // 0-100
  reasoning: string[];
  category: string;
  closeTime: string; // market close time
}

export interface SettledBet extends ActiveBet {
  result: "won" | "lost" | "push";
  payout: number; // cents
  pnl: number; // cents
  settledAt: string;
  learnings: string[];
}

export interface BrainState {
  enabled: boolean;
  mode: "paper" | "live";
  bankroll_cents: number;
  starting_bankroll_cents: number;
  active_bets: ActiveBet[];
  total_bets: number;
  wins: number;
  losses: number;
  total_pnl_cents: number;
  last_cycle: string | null;
  last_bet: string | null;
}

export const DEFAULT_STATE: BrainState = {
  enabled: true,
  mode: "paper",
  bankroll_cents: 10000,
  starting_bankroll_cents: 10000,
  active_bets: [],
  total_bets: 0,
  wins: 0,
  losses: 0,
  total_pnl_cents: 0,
  last_cycle: null,
  last_bet: null,
};

/** Pure: record a new bet in state */
export function recordBet(state: BrainState, bet: ActiveBet): BrainState {
  return {
    ...state,
    active_bets: [...state.active_bets, bet],
    bankroll_cents: state.bankroll_cents - bet.totalCost,
    total_bets: state.total_bets + 1,
    last_bet: new Date().toISOString(),
    last_cycle: new Date().toISOString(),
  };
}

/** Pure: settle a bet and update state */
export function settleBet(
  state: BrainState,
  betId: string,
  result: "won" | "lost" | "push",
  payout: number,
  learnings: string[]
): { state: BrainState; settled: SettledBet | null } {
  const bet = state.active_bets.find((b) => b.id === betId);
  if (!bet) return { state, settled: null };

  const pnl = payout - bet.totalCost;
  const settled: SettledBet = {
    ...bet,
    result,
    payout,
    pnl,
    settledAt: new Date().toISOString(),
    learnings,
  };

  const newState: BrainState = {
    ...state,
    active_bets: state.active_bets.filter((b) => b.id !== betId),
    bankroll_cents: state.bankroll_cents + payout,
    wins: result === "won" ? state.wins + 1 : state.wins,
    losses: result === "lost" ? state.losses + 1 : state.losses,
    total_pnl_cents: state.total_pnl_cents + pnl,
  };

  return { state: newState, settled };
}

export function getWinRate(state: BrainState): number {
  const total = state.wins + state.losses;
  if (total === 0) return 0;
  return (state.wins / total) * 100;
}

export function canPlaceBet(
  state: BrainState,
  thresholds: { max_positions: number; cooldown_hours: number }
): { allowed: boolean; reason?: string } {
  if (!state.enabled) {
    return { allowed: false, reason: "Brain is disabled" };
  }

  if (state.active_bets.length >= thresholds.max_positions) {
    return { allowed: false, reason: `Max positions reached (${thresholds.max_positions})` };
  }

  if (state.last_bet) {
    const hoursSince = (Date.now() - new Date(state.last_bet).getTime()) / (1000 * 60 * 60);
    if (hoursSince < thresholds.cooldown_hours) {
      return {
        allowed: false,
        reason: `Cooldown: ${(thresholds.cooldown_hours - hoursSince).toFixed(1)}h remaining`,
      };
    }
  }

  if (state.bankroll_cents <= 0) {
    return { allowed: false, reason: "Bankroll depleted" };
  }

  return { allowed: true };
}
