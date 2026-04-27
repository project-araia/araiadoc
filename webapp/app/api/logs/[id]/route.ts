import { NextRequest } from "next/server";
import { getJob } from "@/lib/jobs";

export const runtime = "nodejs";

/**
 * GET /api/logs/[id]
 * Server-Sent Events stream of log lines for a job.
 *
 * SSE events:
 *   data: <log line>\n\n         — a new log line
 *   event: done\ndata: <code>\n\n — process finished, data is the exit code
 */
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const job = getJob(id);

  if (!job) {
    return new Response("Job not found", { status: 404 });
  }

  let cursor = 0; // index into job.lines already sent

  const stream = new ReadableStream({
    start(controller) {
      const enc = new TextEncoder();

      const send = (event: string | null, data: string) => {
        let msg = "";
        if (event) msg += `event: ${event}\n`;
        msg += `data: ${data}\n\n`;
        controller.enqueue(enc.encode(msg));
      };

      // Flush any lines that arrived before the client connected
      const flush = () => {
        while (cursor < job.lines.length) {
          send(null, job.lines[cursor]);
          cursor++;
        }
      };

      flush();

      if (job.status !== "running") {
        send("done", String(job.exitCode ?? -1));
        controller.close();
        return;
      }

      // Poll for new lines every 200 ms
      const interval = setInterval(() => {
        flush();

        if (job.status !== "running") {
          send("done", String(job.exitCode ?? -1));
          clearInterval(interval);
          controller.close();
        }
      }, 200);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
