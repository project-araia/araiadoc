import { NextRequest } from "next/server";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const dir = searchParams.get("dir");

  if (!dir) {
    return new Response("Missing dir parameter", { status: 400 });
  }

  // Security: Ensure the directory is inside the 'data' folder of the project
  const projectRoot = path.resolve(process.env.ARAIADOC_ROOT ?? "..");
  const dataDir = path.join(projectRoot, "data");
  const absoluteRequestedDir = path.resolve(dir);

  if (!absoluteRequestedDir.startsWith(dataDir)) {
    return new Response("Unauthorized directory", { status: 403 });
  }

  if (!fs.existsSync(absoluteRequestedDir)) {
    return new Response("Directory not found", { status: 404 });
  }

  const zipProcess = spawn("zip", ["-q", "-r", "-", "."], {
    cwd: absoluteRequestedDir,
  });

  // Drain stderr to prevent the process from blocking on a full pipe buffer
  zipProcess.stderr.resume();

  const stream = new ReadableStream({
    start(controller) {
      zipProcess.stdout.on("data", (chunk) => {
        controller.enqueue(new Uint8Array(chunk));
      });
      zipProcess.on("close", (code) => {
        if (code === 0) {
          controller.close();
        } else {
          controller.error(new Error(`zip process exited with code ${code}`));
        }
      });
      zipProcess.on("error", (err) => {
        controller.error(err);
      });
    },
    cancel() {
      zipProcess.kill();
    },
  });

  const filename = `${path.basename(absoluteRequestedDir)}.zip`;

  return new Response(stream, {
    headers: {
      "Content-Type": "application/zip",
      "Content-Disposition": `attachment; filename="${filename}"`,
      "Cache-Control": "no-cache",
    },
  });
}
