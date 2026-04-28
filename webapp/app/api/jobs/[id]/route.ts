import { NextRequest, NextResponse } from "next/server";
import { getJob } from "@/lib/jobs";

export const runtime = "nodejs";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const job = getJob(id);

  if (!job) {
    return NextResponse.json({ error: "Job not found" }, { status: 404 });
  }

  // Return job info without the circular ChildProcess object
  return NextResponse.json({
    id: job.id,
    tool: job.tool,
    args: job.args,
    status: job.status,
    exitCode: job.exitCode,
    lines: job.lines,
    startedAt: job.startedAt,
  });
}
