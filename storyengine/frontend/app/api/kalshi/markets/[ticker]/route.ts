import { NextResponse } from "next/server";
import { getPublicKalshiClient } from "@/lib/kalshi-server";
import { mockMarkets, getMockOrderbook } from "@/lib/kalshi-mock";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await params;

  try {
    const client = getPublicKalshiClient();
    const [marketData, orderbookData] = await Promise.all([
      client.getMarket(ticker),
      client.getOrderbook(ticker),
    ]);

    return NextResponse.json({
      market: marketData.market,
      orderbook: orderbookData.orderbook,
    });
  } catch {
    // Fallback to mock
    const market = mockMarkets.find((m) => m.ticker === ticker);
    if (!market) {
      return NextResponse.json({ error: "Market not found" }, { status: 404 });
    }

    return NextResponse.json({
      market,
      orderbook: getMockOrderbook(ticker),
      _mock: true,
    });
  }
}
