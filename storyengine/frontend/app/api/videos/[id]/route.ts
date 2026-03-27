import { NextResponse } from "next/server";
import { getSupabaseVideoDetail } from "@/lib/pipeline/supabase-store";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const detail = await getSupabaseVideoDetail(id);

    if (!detail) {
      return NextResponse.json({ error: "Video not found" }, { status: 404 });
    }

    return NextResponse.json(detail);
  } catch (error) {
    console.error("Error fetching Supabase video detail:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Failed to fetch Supabase video detail",
      },
      { status: 500 }
    );
  }
}
