import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { getKalshiClientForUser } from "@/lib/kalshi-server";
import { prisma } from "@/lib/prisma";
import { z } from "zod";

const placeOrderSchema = z.object({
  ticker: z.string().min(1),
  side: z.enum(["yes", "no"]),
  action: z.enum(["buy", "sell"]).default("buy"),
  contracts: z.number().int().min(1).max(1000),
  price: z.number().int().min(1).max(99), // cents
});

export async function POST(req: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const client = await getKalshiClientForUser(userId);

  if (!client) {
    return NextResponse.json(
      { error: "Kalshi account not connected. Go to Settings to connect." },
      { status: 400 }
    );
  }

  const body = await req.json();
  const parsed = placeOrderSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "Invalid order", details: parsed.error.flatten() },
      { status: 400 }
    );
  }

  const { ticker, side, action, contracts, price } = parsed.data;

  try {
    const result = await client.placeOrder({
      ticker,
      side,
      action,
      type: "limit",
      count: contracts,
      yes_price: side === "yes" ? price : undefined,
      no_price: side === "no" ? price : undefined,
    });

    // Log trade locally
    const eventTicker = ticker.split("-").slice(0, -1).join("-");
    await prisma.tradeLog.create({
      data: {
        userId,
        kalshiOrderId: result.order.order_id,
        marketTicker: ticker,
        eventTicker,
        side,
        action,
        contracts,
        pricePerContract: price / 100,
        totalCost: (contracts * price) / 100,
        status: result.order.status === "executed" ? "filled" : "pending",
      },
    });

    return NextResponse.json({ order: result.order });
  } catch (err) {
    return NextResponse.json(
      { error: `Order failed: ${err}` },
      { status: 500 }
    );
  }
}

export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const client = await getKalshiClientForUser(userId);

  if (!client) {
    return NextResponse.json({ orders: [], connected: false });
  }

  try {
    const data = await client.getOrders({ limit: 50 });
    return NextResponse.json({ orders: data.orders, connected: true });
  } catch (err) {
    return NextResponse.json(
      { error: `Failed to fetch orders: ${err}` },
      { status: 500 }
    );
  }
}
