/**
 * Smart market fetching for the betting brain.
 *
 * Fetches markets across multiple pages, filters for relevant categories,
 * and provides settlement lookups for position monitoring.
 *
 * The brain cares about economics, politics, finance — not sports/entertainment.
 */

import type { KalshiMarket } from "../kalshi-types";
import { KalshiClient } from "../kalshi";
import { getPublicKalshiClient } from "../kalshi-server";
import { mockMarkets } from "../kalshi-mock";

/** Categories the brain should analyze (economy/geopolitics focus) */
const RELEVANT_CATEGORIES = new Set([
  "politics",
  "economics",
  "finance",
  "economy",
  "geopolitics",
  "world",
  "climate",
  "energy",
  "tech",
  "science",
  "fed",
  "inflation",
  "gdp",
  "trade",
  "crypto",
]);

/** Check if a market category is relevant to our domain */
function isRelevantCategory(category: string): boolean {
  if (!category) return true; // include uncategorized
  const lower = category.toLowerCase();
  if (RELEVANT_CATEGORIES.has(lower)) return true;
  // Partial match for compound categories like "US Politics"
  return Array.from(RELEVANT_CATEGORIES).some(c => lower.includes(c));
}

/**
 * Fetch markets with pagination, pulling up to `maxPages` pages.
 * Returns all open markets (filtered to relevant categories).
 */
async function fetchAllMarkets(
  client: KalshiClient,
  maxPages: number = 3
): Promise<KalshiMarket[]> {
  const allMarkets: KalshiMarket[] = [];
  let cursor: string | undefined;

  for (let page = 0; page < maxPages; page++) {
    const data = await client.getMarkets({
      cursor,
      limit: 200,
      status: "open",
    });

    allMarkets.push(...data.markets);

    // Stop if no more pages
    if (!data.cursor || data.markets.length === 0) break;
    cursor = data.cursor;
  }

  return allMarkets;
}

/**
 * Fetch markets including settled ones (for monitoring active positions).
 * Settled markets don't show up in status:"open" queries.
 */
async function fetchSettledMarkets(
  client: KalshiClient,
  tickers: string[]
): Promise<KalshiMarket[]> {
  if (tickers.length === 0) return [];

  const results: KalshiMarket[] = [];

  // Fetch each ticker individually — Kalshi doesn't support batch lookup
  // but settled markets can only be fetched by ticker
  const fetches = tickers.map(async (ticker) => {
    try {
      const data = await client.getMarket(ticker);
      return data.market;
    } catch {
      return null;
    }
  });

  const settled = await Promise.all(fetches);
  for (const m of settled) {
    if (m) results.push(m);
  }

  return results;
}

export interface FetchedMarketData {
  /** All open markets in relevant categories for scoring */
  openMarkets: KalshiMarket[];
  /** Markets for active bet tickers (may include settled) */
  positionMarkets: KalshiMarket[];
  /** Combined: all unique markets */
  allMarkets: KalshiMarket[];
  /** Whether we're using mock data */
  isMock: boolean;
}

/**
 * Fetch all market data the brain needs for a cycle + monitoring.
 *
 * @param activeTickers - Tickers of active bets (for settlement checking)
 */
export async function fetchMarketsForBrain(
  activeTickers: string[] = []
): Promise<FetchedMarketData> {
  try {
    const client = getPublicKalshiClient();

    // Fetch open markets (paginated) and position markets in parallel
    const [openRaw, positionMarkets] = await Promise.all([
      fetchAllMarkets(client, 3),
      fetchSettledMarkets(client, activeTickers),
    ]);

    // Filter to relevant categories
    const openMarkets = openRaw.filter((m) => isRelevantCategory(m.category));

    // Combine, dedup by ticker
    const seen = new Set<string>();
    const allMarkets: KalshiMarket[] = [];
    for (const m of [...openMarkets, ...positionMarkets]) {
      if (!seen.has(m.ticker)) {
        seen.add(m.ticker);
        allMarkets.push(m);
      }
    }

    return { openMarkets, positionMarkets, allMarkets, isMock: false };
  } catch (error) {
    console.warn("Kalshi API unavailable, using mock data:", error);

    // Fallback: mock data
    const openMarkets = mockMarkets.filter((m) => m.status === "open");
    return {
      openMarkets,
      positionMarkets: mockMarkets.filter((m) => activeTickers.includes(m.ticker)),
      allMarkets: [...mockMarkets],
      isMock: true,
    };
  }
}
