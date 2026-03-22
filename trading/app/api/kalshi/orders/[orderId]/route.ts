import { NextResponse } from "next/server";
import { getKalshiClientForUser } from "@/lib/kalshi-server";

const DEFAULT_USER_ID = "default-user";

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ orderId: string }> }
) {
  const userId = DEFAULT_USER_ID;
  const client = await getKalshiClientForUser(userId);

  if (!client) {
    return NextResponse.json(
      { error: "Kalshi account not connected" },
      { status: 400 }
    );
  }

  const { orderId } = await params;

  try {
    const result = await client.cancelOrder(orderId);
    return NextResponse.json({ order: result.order });
  } catch (err) {
    return NextResponse.json(
      { error: `Cancel failed: ${err}` },
      { status: 500 }
    );
  }
}
