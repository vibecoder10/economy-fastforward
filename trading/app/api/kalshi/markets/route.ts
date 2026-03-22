import { NextResponse } from "next/server";
import { getPublicKalshiClient } from "@/lib/kalshi-server";
import { mockMarkets } from "@/lib/kalshi-mock";
import { isRelevantCategory } from "@/lib/betting-brain/markets";

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

    // Filter out sports, entertainment, etc. — only relevant categories
    markets = markets.filter((m) => isRelevantCategory(m.category));

    // Filter by category if provided
    if (category && category !== "All") {
      markets = markets.filter(
        (m) => {
          const cat = (m.category || "").toLowerCase();
          const target = category.toLowerCase();
          return cat === target || cat.includes(target) || target.includes(cat);
        }
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
    let markets = mockMarkets.filter((m) => isRelevantCategory(m.category));

    if (category && category !== "All") {
      markets = markets.filter(
        (m) => {
          const cat = (m.category || "").toLowerCase();
          const target = category.toLowerCase();
          return cat === target || cat.includes(target) || target.includes(cat);
        }
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
