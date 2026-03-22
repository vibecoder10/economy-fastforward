import { NextResponse } from "next/server";
import { getKalshiClientForUser } from "@/lib/kalshi-server";
import { mockBalance, mockPositions } from "@/lib/kalshi-mock";

const DEFAULT_USER_ID = "default-user";

export async function GET() {
  const userId = DEFAULT_USER_ID;

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
