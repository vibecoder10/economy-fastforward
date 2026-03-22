import { NextResponse } from "next/server";
import { getPublicKalshiClient } from "@/lib/kalshi-server";
import { mockMarkets } from "@/lib/kalshi-mock";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const category = searchParams.get("category");
  const search = searchParams.get("search")?.toLowerCase();
  const cursor = searchParams.get("cursor") ?? undefined;
  const limit = Number(searchParams.get("limit") ?? 20);

  try {
    const client = getPublicKalshiClient();
    const data = await client.getMarkets({
      cursor,
      limit,
      status: "open",
    });

    let markets = data.markets;

    // Filter by category if provided
    if (category && category !== "All") {
      markets = markets.filter(
        (m) => m.category?.toLowerCase() === category.toLowerCase()
      );
    }

    // Filter by search term
    if (search) {
      markets = markets.filter((m) =>
        m.title.toLowerCase().includes(search)
      );
    }

    return NextResponse.json({ markets, cursor: data.cursor });
  } catch {
    // Fallback to mock data
    let markets = [...mockMarkets];

    if (category && category !== "All") {
      markets = markets.filter(
        (m) => m.category?.toLowerCase() === category.toLowerCase()
      );
    }

    if (search) {
      markets = markets.filter((m) =>
        m.title.toLowerCase().includes(search)
      );
    }

    // Apply pagination
    const startIdx = cursor ? mockMarkets.findIndex((m) => m.ticker === cursor) + 1 : 0;
    const paginated = markets.slice(startIdx, startIdx + limit);

    return NextResponse.json({
      markets: paginated,
      cursor: paginated.length === limit ? paginated[paginated.length - 1]?.ticker : undefined,
      _mock: true,
    });
  }
}
