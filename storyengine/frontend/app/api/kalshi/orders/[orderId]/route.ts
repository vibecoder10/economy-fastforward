import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { getKalshiClientForUser } from "@/lib/kalshi-server";

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ orderId: string }> }
) {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const userId = (session.user as { id: string }).id;
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
