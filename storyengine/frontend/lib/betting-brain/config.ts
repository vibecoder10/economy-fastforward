/**
 * Parse betting_program.md into typed configuration.
 * Mirrors: autopilot/core/config_parser.py
 */

import { readFileSync } from "fs";
import { join } from "path";

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

function extractYamlBlock(
  content: string,
  sectionName: string
): Record<string, string | number | Record<string, number>> {
  const pattern = new RegExp(
    `##\\s+${sectionName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\n([\\s\\S]*?)(?=\\n##|$)`,
    "i"
  );
  const match = content.match(pattern);
  if (!match) return {};

  const sectionContent = match[1];
  const result: Record<string, string | number | Record<string, number>> = {};
  let currentNested: string | null = null;
  let nestedDict: Record<string, number> = {};

  for (const rawLine of sectionContent.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || line.startsWith("---") || line.startsWith("_")) continue;

    // Nested block start (e.g., "weights:")
    if (line.endsWith(":") && !line.slice(0, -1).includes(":")) {
      if (currentNested && Object.keys(nestedDict).length > 0) {
        result[currentNested] = nestedDict;
      }
      currentNested = line.slice(0, -1).trim();
      nestedDict = {};
      continue;
    }

    if (line.includes(":")) {
      const colonIdx = line.indexOf(":");
      const key = line.slice(0, colonIdx).trim();
      const value = line.slice(colonIdx + 1).trim();

      const parsed = value.includes(".") ? parseFloat(value) : parseInt(value, 10);
      const finalValue = isNaN(parsed) ? value : parsed;

      if (currentNested) {
        nestedDict[key] = typeof finalValue === "number" ? finalValue : 0;
      } else {
        result[key] = finalValue;
      }
    }
  }

  if (currentNested && Object.keys(nestedDict).length > 0) {
    result[currentNested] = nestedDict;
  }

  return result;
}

export function parseConfig(content: string): BrainConfig {
  const state = extractYamlBlock(content, "State");
  const weightsSection = extractYamlBlock(content, "Scoring Weights");
  const thresholdsSection = extractYamlBlock(content, "Thresholds");
  const categoriesSection = extractYamlBlock(content, "Categories");

  const weightsData = (weightsSection.weights as Record<string, number>) ?? {};
  const thresholdsData = (thresholdsSection.thresholds as Record<string, number>) ?? {};
  const categoriesData = (categoriesSection.categories as Record<string, number>) ?? {};

  return {
    enabled: String(state.brain ?? "ON").toUpperCase() === "ON",
    mode: String(state.mode ?? "paper") as "paper" | "live",
    starting_bankroll_cents: (state.starting_bankroll_cents as number) ?? 10000,
    weights: { ...DEFAULT_WEIGHTS, ...weightsData },
    thresholds: { ...DEFAULT_THRESHOLDS, ...thresholdsData },
    category_scores: categoriesData,
  };
}

export function loadConfig(): BrainConfig {
  try {
    const configPath = join(__dirname, "betting_program.md");
    const content = readFileSync(configPath, "utf-8");
    return parseConfig(content);
  } catch {
    return {
      enabled: true,
      mode: "paper",
      starting_bankroll_cents: 10000,
      weights: DEFAULT_WEIGHTS,
      thresholds: DEFAULT_THRESHOLDS,
      category_scores: {},
    };
  }
}
