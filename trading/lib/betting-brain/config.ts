/**
 * Betting brain configuration types and defaults.
 *
 * Config is embedded as constants (no filesystem reads).
 * To change: edit the defaults below. Future: store in DB per user.
 * Mirrors: autopilot/core/config_parser.py
 */

export interface BrainWeights {
  price_edge: number;
  volume_signal: number;
  time_to_close: number;
  category_fit: number;
  price_momentum: number;
}

export interface BrainThresholds {
  min_confidence: number;
  min_edge_cents: number;
  max_positions: number;
  take_profit_pct: number;
  max_bet_pct: number;
  min_bet_cents: number;
  cooldown_hours: number;
}

export interface BrainConfig {
  enabled: boolean;
  mode: "paper" | "live";
  starting_bankroll_cents: number;
  weights: BrainWeights;
  thresholds: BrainThresholds;
  category_scores: Record<string, number>;
}

const DEFAULT_WEIGHTS: BrainWeights = {
  price_edge: 0.3,
  volume_signal: 0.2,
  time_to_close: 0.2,
  category_fit: 0.15,
  price_momentum: 0.15,
};

const DEFAULT_THRESHOLDS: BrainThresholds = {
  min_confidence: 60,
  min_edge_cents: 5,
  max_positions: 5,
  take_profit_pct: 0.3,
  max_bet_pct: 0.15,
  min_bet_cents: 100,
  cooldown_hours: 4,
};

export const DEFAULT_CONFIG: BrainConfig = {
  enabled: true,
  mode: "paper",
  starting_bankroll_cents: 10000,
  weights: DEFAULT_WEIGHTS,
  thresholds: DEFAULT_THRESHOLDS,
  category_scores: {},
};

/** Get brain config (with optional category score overrides from learned data) */
export function getConfig(categoryOverrides?: Record<string, number>): BrainConfig {
  return {
    ...DEFAULT_CONFIG,
    category_scores: { ...DEFAULT_CONFIG.category_scores, ...categoryOverrides },
  };
}
