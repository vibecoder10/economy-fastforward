import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { z } from "zod";

const addSchema = z.object({
  eventTicker: z.string().min(1),
  marketTicker: z.string().min(1),
  title: z.string().default(""),
});

// Get watchlist
export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const items = await prisma.watchlistItem.findMany({
    where: { userId },
    orderBy: { addedAt: "desc" },
  });

  return NextResponse.json({ items });
}

// Add to watchlist
export async function POST(req: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const body = await req.json();
  const parsed = addSchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json(
      { error: "Invalid data", details: parsed.error.flatten() },
      { status: 400 }
    );
  }

  const item = await prisma.watchlistItem.upsert({
    where: {
      userId_marketTicker: {
        userId,
        marketTicker: parsed.data.marketTicker,
      },
    },
    create: {
      userId,
      eventTicker: parsed.data.eventTicker,
      marketTicker: parsed.data.marketTicker,
      title: parsed.data.title,
    },
    update: {},
  });

  return NextResponse.json({ item });
}

// Remove from watchlist
export async function DELETE(req: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const { searchParams } = new URL(req.url);
  const marketTicker = searchParams.get("marketTicker");

  if (!marketTicker) {
    return NextResponse.json(
      { error: "marketTicker required" },
      { status: 400 }
    );
  }

  await prisma.watchlistItem.deleteMany({
    where: { userId, marketTicker },
  });

  return NextResponse.json({ success: true });
}
