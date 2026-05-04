import { NextRequest, NextResponse } from "next/server";
import { stopJob } from "@/lib/jobs";

export const runtime = "nodejs";

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const success = stopJob(id);

  if (!success) {
    return NextResponse.json(
      { error: "Failed to cancel job or job already finished" },
      { status: 400 }
    );
  }

  return NextResponse.json({ success: true });
}
