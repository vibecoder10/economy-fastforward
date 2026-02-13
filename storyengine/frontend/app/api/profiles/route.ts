import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { ECONOMY_FASTFORWARD_PROFILE } from "@shared/constants";

export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const profiles = await prisma.channelProfile.findMany({
    where: { userId },
    select: {
      id: true,
      name: true,
      isDefault: true,
      updatedAt: true,
    },
    orderBy: { updatedAt: "desc" },
  });

  return NextResponse.json(profiles);
}

export async function POST(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const body = await request.json();

  const profile = await prisma.channelProfile.create({
    data: {
      userId,
      name: body.name || "New Profile",
      isDefault: false,
      narrativeConfig: JSON.stringify(
        ECONOMY_FASTFORWARD_PROFILE.narrativeConfig
      ),
      visualConfig: JSON.stringify(ECONOMY_FASTFORWARD_PROFILE.visualConfig),
      visualAnchors: JSON.stringify(ECONOMY_FASTFORWARD_PROFILE.visualAnchors),
    },
  });

  return NextResponse.json({ id: profile.id });
}
