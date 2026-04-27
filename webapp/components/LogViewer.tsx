"use client";

import { useEffect, useRef, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";

interface LogViewerProps {
  jobId: string;
  onFinish?: (exitCode: number) => void;
}

export function LogViewer({ jobId, onFinish }: LogViewerProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [status, setStatus] = useState<"running" | "done" | "error">("running");
  const [exitCode, setExitCode] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const es = new EventSource(`/api/logs/${jobId}`);

    es.onmessage = (e) => {
      setLines((prev) => [...prev, e.data]);
    };

    es.addEventListener("done", (e) => {
      const code = parseInt((e as MessageEvent).data ?? "-1", 10);
      setExitCode(code);
      setStatus(code === 0 ? "done" : "error");
      onFinish?.(code);
      es.close();
    });

    es.onerror = () => {
      setStatus("error");
      es.close();
    };

    return () => es.close();
  }, [jobId, onFinish]);

  // Auto-scroll to bottom whenever new lines arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  const statusBadge =
    status === "running" ? (
      <Badge variant="outline" className="text-yellow-400 border-yellow-400 text-xs">
        running
      </Badge>
    ) : status === "done" ? (
      <Badge variant="outline" className="text-green-400 border-green-400 text-xs">
        done (exit 0)
      </Badge>
    ) : (
      <Badge variant="outline" className="text-red-400 border-red-400 text-xs">
        error (exit {exitCode ?? "?"})
      </Badge>
    );

  return (
    <div className="mt-4 space-y-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>Job {jobId.slice(0, 8)}</span>
        {statusBadge}
      </div>
      <ScrollArea className="h-64 w-full rounded-md border border-border bg-black/60 p-3">
        <div className="text-xs leading-relaxed">
          {lines.length === 0 ? (
            <span className="text-muted-foreground">Waiting for output...</span>
          ) : (
            lines.map((line, i) => {
              const isStderr = line.startsWith("[stderr]");
              const isSystem = line.startsWith("[system]");
              return (
                <div
                  key={i}
                  className={
                    isStderr
                      ? "text-red-400"
                      : isSystem
                      ? "text-muted-foreground italic"
                      : "text-green-300"
                  }
                >
                  {line}
                </div>
              );
            })
          )}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
    </div>
  );
}
