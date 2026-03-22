import { NextResponse } from "next/server";
import { getPublicKalshiClient } from "@/lib/kalshi-server";
import { mockEvents } from "@/lib/kalshi-mock";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const cursor = searchParams.get("cursor") ?? undefined;
  const limit = Number(searchParams.get("limit") ?? 20);

  try {
    const client = getPublicKalshiClient();
    const data = await client.getEvents({
      cursor,
      limit,
      status: "open",
      with_nested_markets: true,
    });
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({
      events: mockEvents,
      _mock: true,
    });
  }
}
