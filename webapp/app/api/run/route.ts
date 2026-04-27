import { NextRequest, NextResponse } from "next/server";
import { spawnAraiadoc } from "@/lib/spawn";

export const runtime = "nodejs";

/**
 * POST /api/run
 * Body: { tool: string, args: string[] }
 * Returns: { jobId: string }
 */
export async function POST(req: NextRequest) {
  let body: { tool: string; args: string[] };

  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const { tool, args } = body;

  if (!tool || typeof tool !== "string") {
    return NextResponse.json({ error: "Missing or invalid `tool` field" }, { status: 400 });
  }

  if (!Array.isArray(args) || !args.every((a) => typeof a === "string")) {
    return NextResponse.json({ error: "`args` must be an array of strings" }, { status: 400 });
  }

  const allowedTools = [
    "crawl-epa",
    "crawl-osti",
    "complete-semantic-scholar",
    "convert",
    "get-from-titanv",
  ];

  if (!allowedTools.includes(tool)) {
    return NextResponse.json({ error: `Tool "${tool}" is not allowed` }, { status: 400 });
  }

  const job = spawnAraiadoc(tool, args);

  return NextResponse.json({ jobId: job.id }, { status: 202 });
}
