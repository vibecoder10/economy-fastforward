import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { encrypt, decrypt } from "@/lib/crypto";
import { KalshiClient } from "@/lib/kalshi";
import { z } from "zod";

const credentialSchema = z.object({
  apiKeyId: z.string().min(1, "API Key ID is required"),
  privateKey: z.string().min(1, "Private Key is required"),
});

// Check if credentials are configured
export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const creds = await prisma.kalshiCredentials.findUnique({
    where: { userId },
  });

  return NextResponse.json({
    configured: !!creds,
    updatedAt: creds?.updatedAt ?? null,
  });
}

// Save credentials (encrypted)
export async function PUT(req: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const body = await req.json();
  const parsed = credentialSchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json(
      { error: "Invalid credentials", details: parsed.error.flatten() },
      { status: 400 }
    );
  }

  const { apiKeyId, privateKey } = parsed.data;

  // Test the connection before saving
  try {
    const testClient = new KalshiClient({ apiKeyId, privateKey });
    await testClient.getBalance();
  } catch (err) {
    return NextResponse.json(
      {
        error: "Connection test failed. Please verify your API Key ID and Private Key.",
        details: String(err),
      },
      { status: 400 }
    );
  }

  // Encrypt and save
  const encryptedKeyId = encrypt(apiKeyId);
  const encryptedPrivateKey = encrypt(privateKey);

  await prisma.kalshiCredentials.upsert({
    where: { userId },
    create: {
      userId,
      apiKeyId: encryptedKeyId,
      privateKey: encryptedPrivateKey,
    },
    update: {
      apiKeyId: encryptedKeyId,
      privateKey: encryptedPrivateKey,
    },
  });

  return NextResponse.json({ success: true });
}

// Remove credentials
export async function DELETE() {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;

  await prisma.kalshiCredentials.deleteMany({
    where: { userId },
  });

  return NextResponse.json({ success: true });
}
