import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { encrypt } from "@/lib/crypto";
import { z } from "zod";

const DEFAULT_USER_ID = "default-user";
const KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2";

const loginSchema = z.object({
  email: z.string().email("Valid email required"),
  password: z.string().min(1, "Password required"),
});

/**
 * Sign in with Kalshi email + password.
 * 1. POST /login to get a session token
 * 2. POST /api_keys/generate to create an RSA key pair
 * 3. Store the generated keys encrypted in our DB
 */
export async function POST(req: Request) {
  const userId = DEFAULT_USER_ID;
  const body = await req.json();
  const parsed = loginSchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json(
      { error: "Invalid input", details: parsed.error.flatten() },
      { status: 400 }
    );
  }

  const { email, password } = parsed.data;

  // Step 1: Login to Kalshi to get a session token
  let token: string;
  try {
    const loginRes = await fetch(`${KALSHI_API_BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    if (!loginRes.ok) {
      const text = await loginRes.text().catch(() => "");
      if (loginRes.status === 401 || loginRes.status === 403) {
        return NextResponse.json(
          { error: "Invalid Kalshi email or password. Please try again." },
          { status: 401 }
        );
      }
      return NextResponse.json(
        { error: `Kalshi login failed (${loginRes.status}): ${text}` },
        { status: 400 }
      );
    }

    const loginData = await loginRes.json();
    token = loginData.token;

    if (!token) {
      return NextResponse.json(
        { error: "Kalshi login succeeded but no token returned" },
        { status: 500 }
      );
    }
  } catch (err) {
    return NextResponse.json(
      { error: `Could not reach Kalshi: ${String(err)}` },
      { status: 502 }
    );
  }

  // Step 2: Generate API keys using the session token
  let apiKeyId: string;
  let privateKey: string;
  try {
    const keyRes = await fetch(`${KALSHI_API_BASE}/api_keys/generate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        name: `StoryEngine Trading (${new Date().toISOString().slice(0, 10)})`,
        scopes: ["read", "write"],
      }),
    });

    if (!keyRes.ok) {
      const text = await keyRes.text().catch(() => "");
      return NextResponse.json(
        { error: `Failed to generate API keys: ${text}` },
        { status: 400 }
      );
    }

    const keyData = await keyRes.json();
    apiKeyId = keyData.api_key_id;
    privateKey = keyData.private_key;

    if (!apiKeyId || !privateKey) {
      return NextResponse.json(
        { error: "API key generation returned incomplete data" },
        { status: 500 }
      );
    }
  } catch (err) {
    return NextResponse.json(
      { error: `Key generation failed: ${String(err)}` },
      { status: 502 }
    );
  }

  // Step 3: Store encrypted credentials
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
