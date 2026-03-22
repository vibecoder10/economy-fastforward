import { prisma } from "./prisma";
import { decrypt } from "./crypto";
import { KalshiClient } from "./kalshi";

/**
 * Get an authenticated Kalshi client for a user.
 * Returns null if the user has no Kalshi credentials configured.
 */
export async function getKalshiClientForUser(
  userId: string
): Promise<KalshiClient | null> {
  const creds = await prisma.kalshiCredentials.findUnique({
    where: { userId },
  });

  if (!creds) return null;

  try {
    const apiKeyId = decrypt(creds.apiKeyId);
    const privateKey = decrypt(creds.privateKey);
    return new KalshiClient({ apiKeyId, privateKey });
  } catch {
    console.error("Failed to decrypt Kalshi credentials for user", userId);
    return null;
  }
}

/**
 * Get a public (unauthenticated) Kalshi client for market data.
 */
export function getPublicKalshiClient(): KalshiClient {
  return new KalshiClient();
}

/**
 * Check if a user has Kalshi credentials configured.
 */
export async function isKalshiConfigured(userId: string): Promise<boolean> {
  const count = await prisma.kalshiCredentials.count({
    where: { userId },
  });
  return count > 0;
}
