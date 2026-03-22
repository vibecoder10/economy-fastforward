import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { computeCategoryScores, generateLearningSummary } from "@/lib/betting-brain/learner";

const DEFAULT_USER_ID = "default-user";

/**
 * GET /api/trading/brain/history — Full experiment history + learned patterns
 */
export async function GET() {
  try {
    const userId = DEFAULT_USER_ID;

    // Get all experiments
    const experiments = await prisma.betExperiment.findMany({
      where: { userId },
      orderBy: { createdAt: "desc" },
      take: 50,
    });

    // Compute learned patterns
    const settled = experiments.filter((e) => e.result !== null);
    const categoryScores = computeCategoryScores(
      settled.map((e) => ({ category: e.category, result: e.result }))
    );

    // Aggregate stats
    const totalBets = experiments.length;
    const wins = settled.filter((e) => e.result === "won").length;
    const losses = settled.filter((e) => e.result === "lost").length;
    const totalPnl = settled.reduce((sum, e) => sum + (e.pnl ?? 0), 0);

    // Price range performance
    const priceRanges: Record<string, { wins: number; total: number }> = {};
    for (const exp of settled) {
      const range = exp.entryPrice < 20 ? "cheap" : exp.entryPrice <= 50 ? "mid" : "expensive";
      priceRanges[range] = priceRanges[range] ?? { wins: 0, total: 0 };
      priceRanges[range].total++;
      if (exp.result === "won") priceRanges[range].wins++;
    }

    // Generate learning summary
    const learningSummary = generateLearningSummary(
      settled.map((e) => ({
        category: e.category,
        result: e.result,
        entryPrice: e.entryPrice,
        confidence: e.confidence,
        pnl: e.pnl,
        title: e.title,
      }))
    );

    return NextResponse.json({
      learningSummary,
      experiments: experiments.map((e) => ({
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
        mode: e.mode,
        result: e.result,
        payout: e.payout,
        pnl: e.pnl,
        learnings: e.learnings ? JSON.parse(e.learnings) : null,
        settledAt: e.settledAt?.toISOString() ?? null,
        createdAt: e.createdAt.toISOString(),
      })),
      patterns: {
        categoryScores,
        priceRanges,
      },
      summary: {
        totalBets,
        wins,
        losses,
        winRate: wins + losses > 0 ? Math.round((wins / (wins + losses)) * 100) : 0,
        totalPnlCents: totalPnl,
        totalPnlDollars: totalPnl / 100,
      },
    });
  } catch (error) {
    return NextResponse.json({ error: `History failed: ${error}` }, { status: 500 });
  }
}
