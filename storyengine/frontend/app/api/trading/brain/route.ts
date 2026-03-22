import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { getPublicKalshiClient } from "@/lib/kalshi-server";
import { mockMarkets } from "@/lib/kalshi-mock";
import { getConfig } from "@/lib/betting-brain/config";
import { type BrainState, type ActiveBet, DEFAULT_STATE } from "@/lib/betting-brain/state";
import { runCycle, monitorPositions, getStatus } from "@/lib/betting-brain/brain";
import { extractLearnings, computeCategoryScores } from "@/lib/betting-brain/learner";
import type { KalshiMarket } from "@/lib/kalshi-types";

// ---------- Prisma ↔ BrainState helpers ----------

async function loadStateFromDb(userId: string): Promise<BrainState> {
  const row = await prisma.brainState.findUnique({ where: { userId } });
  if (!row) return { ...DEFAULT_STATE };

  return {
    enabled: row.enabled,
    mode: row.mode as "paper" | "live",
    bankroll_cents: row.bankrollCents,
    starting_bankroll_cents: row.startingBankrollCents,
    active_bets: JSON.parse(row.activeBets) as ActiveBet[],
    total_bets: row.totalBets,
    wins: row.wins,
    losses: row.losses,
    total_pnl_cents: row.totalPnlCents,
    last_cycle: row.lastCycle?.toISOString() ?? null,
    last_bet: row.lastBet?.toISOString() ?? null,
  };
}

async function saveStateToDb(userId: string, state: BrainState): Promise<void> {
  await prisma.brainState.upsert({
    where: { userId },
    create: {
      userId,
      enabled: state.enabled,
      mode: state.mode,
      bankrollCents: state.bankroll_cents,
      startingBankrollCents: state.starting_bankroll_cents,
      activeBets: JSON.stringify(state.active_bets),
      totalBets: state.total_bets,
      wins: state.wins,
      losses: state.losses,
      totalPnlCents: state.total_pnl_cents,
      lastCycle: state.last_cycle ? new Date(state.last_cycle) : null,
      lastBet: state.last_bet ? new Date(state.last_bet) : null,
    },
    update: {
      enabled: state.enabled,
      mode: state.mode,
      bankrollCents: state.bankroll_cents,
      startingBankrollCents: state.starting_bankroll_cents,
      activeBets: JSON.stringify(state.active_bets),
      totalBets: state.total_bets,
      wins: state.wins,
      losses: state.losses,
      totalPnlCents: state.total_pnl_cents,
      lastCycle: state.last_cycle ? new Date(state.last_cycle) : null,
      lastBet: state.last_bet ? new Date(state.last_bet) : null,
    },
  });
}

async function fetchMarkets(): Promise<KalshiMarket[]> {
  try {
    const client = getPublicKalshiClient();
    const data = await client.getMarkets({ status: "open", limit: 100 });
    return data.markets;
  } catch {
    return [...mockMarkets];
  }
}

async function getConfigWithLearnings(userId: string) {
  // Load learned category scores from settled experiments
  const experiments = await prisma.betExperiment.findMany({
    where: { userId, result: { not: null } },
    select: { category: true, result: true },
  });
  const categoryScores = computeCategoryScores(experiments);
  return getConfig(categoryScores);
}

// ---------- GET: Brain status ----------

export async function GET() {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    const userId = (session.user as { id: string }).id;

    const config = await getConfigWithLearnings(userId);
    const state = await loadStateFromDb(userId);
    const status = getStatus(config, state);

    // Get recent settled experiments from DB
    const recentSettled = await prisma.betExperiment.findMany({
      where: { userId, result: { not: null } },
      orderBy: { settledAt: "desc" },
      take: 10,
    });

    return NextResponse.json({
      status,
      activeBets: state.active_bets,
      recentSettled: recentSettled.map((e) => ({
        id: e.id,
        ticker: e.ticker,
        title: e.title,
        side: e.side,
        contracts: e.contracts,
        entryPrice: e.entryPrice,
        totalCost: e.totalCost,
        confidence: e.confidence,
        reasoning: JSON.parse(e.reasoning),
        category: e.category,
        closeTime: "",
        placedAt: e.createdAt.toISOString(),
        result: e.result,
        payout: e.payout,
        pnl: e.pnl,
        settledAt: e.settledAt?.toISOString() ?? "",
        learnings: e.learnings ? JSON.parse(e.learnings) : [],
      })),
      config: {
        mode: config.mode,
        weights: config.weights,
        thresholds: config.thresholds,
      },
    });
  } catch (error) {
    return NextResponse.json({ error: `Brain status failed: ${error}` }, { status: 500 });
  }
}

// ---------- POST: Run actions ----------

export async function POST(req: Request) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    const userId = (session.user as { id: string }).id;

    const body = await req.json();
    const action = body.action as string;
    const config = await getConfigWithLearnings(userId);

    switch (action) {
      case "cycle":
      case "force": {
        let state = await loadStateFromDb(userId);
        const markets = await fetchMarkets();

        // Force: override cooldown
        if (action === "force") {
          state = { ...state, last_bet: null };
        }

        const result = runCycle(markets, config, state);

        // Persist updated state
        await saveStateToDb(userId, result.state);

        // If bet placed, also create BetExperiment record
        if (result.action === "bet_placed" && result.bet) {
          await prisma.betExperiment.create({
            data: {
              userId,
              ticker: result.bet.ticker,
              title: result.bet.title,
              side: result.bet.side,
              contracts: result.bet.contracts,
              entryPrice: result.bet.entryPrice,
              totalCost: result.bet.totalCost,
              confidence: result.bet.confidence,
              reasoning: JSON.stringify(result.bet.reasoning),
              category: result.bet.category,
              mode: config.mode,
            },
          });
        }

        return NextResponse.json({
          action: result.action,
          reason: result.reason,
          bet: result.bet,
          rankings: result.rankings?.slice(0, 5),
          state: getStatus(config, result.state),
        });
      }

      case "monitor": {
        const state = await loadStateFromDb(userId);
        const markets = await fetchMarkets();
        const result = monitorPositions(markets, state);

        // Persist updated state
        await saveStateToDb(userId, result.state);

        // For each settlement, extract learnings and persist
        for (const s of result.settlements) {
          const learnings = extractLearnings(s.settled);

          // Update BetExperiment with result + learnings
          const experiment = await prisma.betExperiment.findFirst({
            where: { userId, ticker: s.ticker, result: null },
            orderBy: { createdAt: "desc" },
          });
          if (experiment) {
            await prisma.betExperiment.update({
              where: { id: experiment.id },
              data: {
                result: s.result,
                payout: s.settled.payout,
                pnl: s.pnl,
                learnings: JSON.stringify(learnings),
                settledAt: new Date(),
              },
            });
          }
        }

        return NextResponse.json({
          settlements: result.settlements.map((s) => ({
            betId: s.betId,
            ticker: s.ticker,
            result: s.result,
            pnl: s.pnl,
          })),
          active: result.active,
          state: getStatus(config, result.state),
        });
      }

      case "toggle": {
        const enabled = body.enabled as boolean;
        const state = await loadStateFromDb(userId);
        const newState = { ...state, enabled };
        await saveStateToDb(userId, newState);

        return NextResponse.json({
          enabled: newState.enabled,
          message: `Brain ${enabled ? "enabled" : "disabled"}`,
        });
      }

      default:
        return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 400 });
    }
  } catch (error) {
    return NextResponse.json({ error: `Brain action failed: ${error}` }, { status: 500 });
  }
}
