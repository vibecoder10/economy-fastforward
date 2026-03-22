import { NextResponse } from "next/server";
import { getPublicKalshiClient } from "@/lib/kalshi-server";
import { mockMarkets } from "@/lib/kalshi-mock";
import { loadConfig } from "@/lib/betting-brain/config";
import { loadState, saveState } from "@/lib/betting-brain/state";
import {
  runCycle,
  monitorPositions,
  getStatus,
  forceCycle,
  toggleBrain,
} from "@/lib/betting-brain/brain";
import { extractLearnings, writeLearnings } from "@/lib/betting-brain/learner";
import type { KalshiMarket } from "@/lib/kalshi-types";

async function fetchMarkets(): Promise<KalshiMarket[]> {
  try {
    const client = getPublicKalshiClient();
    const data = await client.getMarkets({ status: "open", limit: 100 });
    return data.markets;
  } catch {
    return [...mockMarkets];
  }
}

/**
 * GET /api/trading/brain — Get brain status + active bets
 */
export async function GET() {
  try {
    const config = loadConfig();
    const state = loadState();
    const status = getStatus(config, state);

    return NextResponse.json({
      status,
      activeBets: state.active_bets,
      recentSettled: state.settled_bets.slice(-10),
      config: {
        mode: config.mode,
        weights: config.weights,
        thresholds: config.thresholds,
      },
    });
  } catch (error) {
    return NextResponse.json(
      { error: `Brain status failed: ${error}` },
      { status: 500 }
    );
  }
}

/**
 * POST /api/trading/brain — Run a cycle or perform an action
 *
 * Body: { action: "cycle" | "force" | "monitor" | "toggle", enabled?: boolean }
 */
export async function POST(req: Request) {
  try {
    const body = await req.json();
    const action = body.action as string;
    const config = loadConfig();

    switch (action) {
      case "cycle": {
        const markets = await fetchMarkets();
        const result = runCycle(markets, config);

        // If a bet was placed and markets settled, extract learnings
        if (result.action === "bet_placed") {
          const monitorResult = monitorPositions(markets);
          for (const settled of monitorResult.settled) {
            const state = loadState();
            const settledBet = state.settled_bets.find((b) => b.id === settled.betId);
            if (settledBet) {
              const learnings = extractLearnings(settledBet);
              writeLearnings(settledBet, learnings);
            }
          }
        }

        return NextResponse.json(result);
      }

      case "force": {
        const markets = await fetchMarkets();
        const result = forceCycle(markets, config);
        return NextResponse.json(result);
      }

      case "monitor": {
        const markets = await fetchMarkets();
        const state = loadState();
        const monitorResult = monitorPositions(markets, state);

        // Extract learnings for any newly settled bets
        const updatedState = loadState();
        for (const settled of monitorResult.settled) {
          const settledBet = updatedState.settled_bets.find((b) => b.id === settled.betId);
          if (settledBet) {
            const learnings = extractLearnings(settledBet);
            writeLearnings(settledBet, learnings);
          }
        }

        return NextResponse.json(monitorResult);
      }

      case "toggle": {
        const enabled = body.enabled as boolean;
        const state = toggleBrain(enabled);
        return NextResponse.json({
          enabled: state.enabled,
          message: `Brain ${enabled ? "enabled" : "disabled"}`,
        });
      }

      default:
        return NextResponse.json(
          { error: `Unknown action: ${action}` },
          { status: 400 }
        );
    }
  } catch (error) {
    return NextResponse.json(
      { error: `Brain action failed: ${error}` },
      { status: 500 }
    );
  }
}
