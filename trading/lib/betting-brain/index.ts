/**
 * Betting Brain — Prediction Market Intelligence System
 *
 * Architecture mirrors autopilot/autopilot.py:
 *   Score markets → Size position → Place bet → Monitor → Learn → Repeat
 *
 * Every bet is an experiment. Every outcome is data.
 */

export { getConfig, DEFAULT_CONFIG } from "./config";
export type { BrainConfig, BrainWeights, BrainThresholds } from "./config";

export { DEFAULT_STATE, recordBet, settleBet, getWinRate, canPlaceBet } from "./state";
export type { BrainState, ActiveBet, SettledBet } from "./state";

export { scoreMarket, rankMarkets, getBestMarket } from "./scorer";
export type { MarketCandidate, ScoredMarket } from "./scorer";

export { calculateSize } from "./sizer";
export type { PositionSize } from "./sizer";

export { runCycle, monitorPositions, getStatus } from "./brain";
export type { CycleResult, MonitorResult, BrainStatus, SettlementResult } from "./brain";

export { extractLearnings, computeCategoryScores } from "./learner";
export type { ExtractedLearning } from "./learner";

export { fetchMarketsForBrain } from "./markets";
export type { FetchedMarketData } from "./markets";
