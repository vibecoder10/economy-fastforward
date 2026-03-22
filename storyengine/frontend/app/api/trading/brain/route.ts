import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { getKalshiClientForUser } from "@/lib/kalshi-server";
import { getConfig } from "@/lib/betting-brain/config";
import { type BrainState, type ActiveBet, DEFAULT_STATE } from "@/lib/betting-brain/state";
import { runCycle, monitorPositions, getStatus } from "@/lib/betting-brain/brain";
import { extractLearnings, computeCategoryScores } from "@/lib/betting-brain/learner";
import { fetchMarketsForBrain } from "@/lib/betting-brain/markets";

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

        // Fetch markets with smart filtering + pagination
        const activeTickers = state.active_bets.map((b) => b.ticker);
        const marketData = await fetchMarketsForBrain(activeTickers);

        // Force: override cooldown
        if (action === "force") {
          state = { ...state, last_bet: null };
        }

        // Run cycle against relevant open markets
        const result = runCycle(marketData.openMarkets, config, state);

        // Persist updated state
        await saveStateToDb(userId, result.state);

        // If bet placed, create experiment record + optionally place live order
        let liveOrderId: string | null = null;
        let liveError: string | null = null;

        if (result.action === "bet_placed" && result.bet) {
          // Live mode: actually place the order via Kalshi API
          if (state.mode === "live") {
            const kalshiClient = await getKalshiClientForUser(userId);
            if (!kalshiClient) {
              liveError = "Live mode requires Kalshi credentials. Connect in Settings.";
            } else {
              try {
                const order = await kalshiClient.placeOrder({
                  ticker: result.bet.ticker,
                  side: result.bet.side,
                  action: "buy",
                  type: "limit",
                  count: result.bet.contracts,
                  yes_price: result.bet.side === "yes" ? result.bet.entryPrice : undefined,
                  no_price: result.bet.side === "no" ? result.bet.entryPrice : undefined,
                });
                liveOrderId = order.order.order_id;

                // Log to trade log
                await prisma.tradeLog.create({
                  data: {
                    userId,
                    kalshiOrderId: order.order.order_id,
                    marketTicker: result.bet.ticker,
                    eventTicker: result.bet.ticker.split("-").slice(0, -1).join("-"),
                    side: result.bet.side,
                    action: "buy",
                    contracts: result.bet.contracts,
                    pricePerContract: result.bet.entryPrice / 100,
                    totalCost: result.bet.totalCost / 100,
                    status: order.order.status === "executed" ? "filled" : "pending",
                  },
                });
              } catch (err) {
                liveError = `Order failed: ${err}`;
                // Revert the bet from state since it wasn't actually placed
                const revertedState = {
                  ...result.state,
                  active_bets: result.state.active_bets.filter((b) => b.id !== result.bet!.id),
                  bankroll_cents: result.state.bankroll_cents + result.bet.totalCost,
                  total_bets: result.state.total_bets - 1,
                };
                await saveStateToDb(userId, revertedState);
              }
            }
          }

          // Create experiment record (paper or live)
          if (!liveError) {
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
                mode: state.mode,
              },
            });
          }
        }

        return NextResponse.json({
          action: liveError ? "error" : result.action,
          reason: liveError ?? result.reason,
          bet: liveError ? undefined : result.bet,
          liveOrderId,
          rankings: result.rankings?.slice(0, 5),
          marketsScanned: marketData.openMarkets.length,
          isMock: marketData.isMock,
          state: getStatus(config, liveError ? await loadStateFromDb(userId) : result.state),
        });
      }

      case "monitor": {
        const state = await loadStateFromDb(userId);

        // Fetch all markets including settled ones for active positions
        const activeTickers = state.active_bets.map((b) => b.ticker);
        const marketData = await fetchMarketsForBrain(activeTickers);
        const result = monitorPositions(marketData.allMarkets, state);

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

      case "set-mode": {
        const mode = body.mode as string;
        if (mode !== "paper" && mode !== "live") {
          return NextResponse.json({ error: "Mode must be 'paper' or 'live'" }, { status: 400 });
        }

        // Require Kalshi credentials for live mode
        if (mode === "live") {
          const kalshiClient = await getKalshiClientForUser(userId);
          if (!kalshiClient) {
            return NextResponse.json(
              { error: "Live mode requires Kalshi credentials. Connect in Settings first." },
              { status: 400 }
            );
          }
        }

        const state = await loadStateFromDb(userId);
        const newState = { ...state, mode: mode as "paper" | "live" };
        await saveStateToDb(userId, newState);

        return NextResponse.json({
          mode: newState.mode,
          message: `Switched to ${mode} trading`,
        });
      }

      default:
        return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 400 });
    }
  } catch (error) {
    return NextResponse.json({ error: `Brain action failed: ${error}` }, { status: 500 });
  }
}
