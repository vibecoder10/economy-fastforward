import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { getKalshiClientForUser } from "@/lib/kalshi-server";
import { mockBalance, mockPositions } from "@/lib/kalshi-mock";

export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;

  try {
    const client = await getKalshiClientForUser(userId);
    if (!client) {
      // No credentials — return mock for demo
      return NextResponse.json({
        balance: mockBalance,
        positions: mockPositions,
        connected: false,
        _mock: true,
      });
    }

    const [balanceData, positionsData] = await Promise.all([
      client.getBalance(),
      client.getPositions({ settlement_status: "unsettled" }),
    ]);

    return NextResponse.json({
      balance: balanceData,
      positions: positionsData.market_positions,
      connected: true,
    });
  } catch (err) {
    return NextResponse.json(
      { error: `Failed to fetch portfolio: ${err}` },
      { status: 500 }
    );
  }
}
