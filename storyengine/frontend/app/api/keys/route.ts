import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { encrypt } from "@/lib/crypto";

export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const keys = await prisma.apiKeys.findUnique({ where: { userId } });

  return NextResponse.json({
    anthropicKey: !!keys?.anthropicKey,
    kieAiKey: !!keys?.kieAiKey,
    elevenLabsKey: !!keys?.elevenLabsKey,
  });
}

export async function PUT(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const body = await request.json();

  const data: Record<string, string> = {};

  if (body.anthropicKey) {
    data.anthropicKey = encrypt(body.anthropicKey);
  }
  if (body.kieAiKey) {
    data.kieAiKey = encrypt(body.kieAiKey);
  }
  if (body.elevenLabsKey) {
    data.elevenLabsKey = encrypt(body.elevenLabsKey);
  }

  if (Object.keys(data).length === 0) {
    return NextResponse.json({ error: "No keys provided" }, { status: 400 });
  }

  await prisma.apiKeys.upsert({
    where: { userId },
    update: data,
    create: { userId, ...data },
  });

  return NextResponse.json({ success: true });
}
