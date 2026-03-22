/**
 * Betting Brain — Prediction Market Intelligence System
 *
 * Architecture mirrors autopilot/autopilot.py:
 *   Score markets → Size position → Place bet → Monitor → Learn → Repeat
 *
 * Every bet is an experiment. Every outcome is data.
 */

export { parseConfig, loadConfig } from "./config";
export type { BrainConfig, BrainWeights, BrainThresholds } from "./config";

export { loadState, saveState, recordBet, settleBet, getWinRate, canPlaceBet } from "./state";
export type { BrainState, ActiveBet, SettledBet } from "./state";

export { scoreMarket, rankMarkets, getBestMarket } from "./scorer";
export type { MarketCandidate, ScoredMarket } from "./scorer";

export { calculateSize } from "./sizer";
export type { PositionSize } from "./sizer";

export { runCycle, monitorPositions, getStatus, forceCycle, toggleBrain } from "./brain";
export type { CycleResult, MonitorResult, BrainStatus } from "./brain";

export { extractLearnings, writeLearnings, getCategoryWinRates } from "./learner";
export type { ExtractedLearning } from "./learner";
