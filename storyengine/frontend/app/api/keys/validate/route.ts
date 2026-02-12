import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { decrypt } from "@/lib/crypto";

export async function POST(request: Request) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
  const { keyType } = await request.json();

  const keys = await prisma.apiKeys.findUnique({ where: { userId } });
  if (!keys) {
    return NextResponse.json(
      { valid: false, error: "No keys configured" },
      { status: 400 }
    );
  }

  try {
    switch (keyType) {
      case "anthropic": {
        if (!keys.anthropicKey) {
          return NextResponse.json({
            valid: false,
            error: "Key not configured",
          });
        }
        const apiKey = decrypt(keys.anthropicKey);
        // Test with a minimal request
        const res = await fetch("https://api.anthropic.com/v1/messages", {
          method: "POST",
          headers: {
            "x-api-key": apiKey,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            model: "claude-sonnet-4-5-20250929",
            max_tokens: 1,
            messages: [{ role: "user", content: "hi" }],
          }),
        });
        return NextResponse.json({ valid: res.ok });
      }

      case "kieAi": {
        if (!keys.kieAiKey) {
          return NextResponse.json({
            valid: false,
            error: "Key not configured",
          });
        }
        // Kie.ai doesn't have a dedicated test endpoint, so we just verify the key format
        const kieKey = decrypt(keys.kieAiKey);
        return NextResponse.json({ valid: kieKey.length > 10 });
      }

      case "elevenLabs": {
        if (!keys.elevenLabsKey) {
          return NextResponse.json({
            valid: false,
            error: "Key not configured",
          });
        }
        const elKey = decrypt(keys.elevenLabsKey);
        return NextResponse.json({ valid: elKey.length > 10 });
      }

      default:
        return NextResponse.json(
          { valid: false, error: "Unknown key type" },
          { status: 400 }
        );
    }
  } catch (error) {
    return NextResponse.json({
      valid: false,
      error: error instanceof Error ? error.message : "Validation failed",
    });
  }
}
