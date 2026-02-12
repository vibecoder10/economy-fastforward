import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET(
  _request: Request,
  { params }: { params: { id: string } }
) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const profile = await prisma.channelProfile.findFirst({
    where: { id: params.id, userId },
  });

  if (!profile) {
    return NextResponse.json({ error: "Profile not found" }, { status: 404 });
  }

  return NextResponse.json({
    id: profile.id,
    name: profile.name,
    isDefault: profile.isDefault,
    narrativeConfig: JSON.parse(profile.narrativeConfig),
    visualConfig: JSON.parse(profile.visualConfig),
    visualAnchors: JSON.parse(profile.visualAnchors),
  });
}

export async function PUT(
  request: Request,
  { params }: { params: { id: string } }
) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const body = await request.json();

  // Verify ownership
  const existing = await prisma.channelProfile.findFirst({
    where: { id: params.id, userId },
  });

  if (!existing) {
    return NextResponse.json({ error: "Profile not found" }, { status: 404 });
  }

  const updated = await prisma.channelProfile.update({
    where: { id: params.id },
    data: {
      name: body.name,
      narrativeConfig: JSON.stringify(body.narrativeConfig),
      visualConfig: JSON.stringify(body.visualConfig),
      visualAnchors: JSON.stringify(body.visualAnchors),
    },
  });

  return NextResponse.json({ id: updated.id });
}

export async function DELETE(
  _request: Request,
  { params }: { params: { id: string } }
) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;

  const profile = await prisma.channelProfile.findFirst({
    where: { id: params.id, userId },
  });

  if (!profile) {
    return NextResponse.json({ error: "Profile not found" }, { status: 404 });
  }

  if (profile.isDefault) {
    return NextResponse.json(
      { error: "Cannot delete default profile" },
      { status: 400 }
    );
  }

  await prisma.channelProfile.delete({ where: { id: params.id } });

  return NextResponse.json({ success: true });
}
