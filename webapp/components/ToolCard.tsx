"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { LogViewer } from "@/components/LogViewer";
import { Badge } from "@/components/ui/badge";

interface ToolCardProps {
  title: string;
  description: string;
  tool: string;
  children: (props: { disabled: boolean }) => React.ReactNode;
  buildArgs: () => string[] | null; // returns null if validation fails
}

export function ToolCard({
  title,
  description,
  tool,
  children,
  buildArgs,
}: ToolCardProps) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobHistory, setJobHistory] = useState<string[]>([]);

  const handleRun = async () => {
    setError(null);
    const args = buildArgs();
    if (args === null) return; // validation handled by child

    setIsRunning(true);

    try {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool, args }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error ?? `HTTP ${res.status}`);
      }

      const { jobId: newId } = await res.json();
      setJobId(newId);
      setJobHistory((prev) => [newId, ...prev]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setIsRunning(false);
    }
  };

  const handleFinish = (exitCode: number) => {
    setIsRunning(false);
    if (exitCode !== 0) {
      setError(`Process exited with code ${exitCode}`);
    }
  };

  return (
    <Card className="bg-card border-border">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle className="text-base font-semibold">{title}</CardTitle>
            <CardDescription className="text-xs mt-1">{description}</CardDescription>
          </div>
          <Badge variant="secondary" className="text-xs font-mono shrink-0">
            {tool}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {children({ disabled: isRunning })}

        {error && (
          <p className="text-xs text-red-400 border border-red-400/30 rounded px-2 py-1 bg-red-400/5">
            {error}
          </p>
        )}

        <Button
          onClick={handleRun}
          disabled={isRunning}
          className="w-full"
          size="sm"
        >
          {isRunning ? "Running..." : "Run"}
        </Button>

        {jobId && (
          <LogViewer key={jobId} jobId={jobId} onFinish={handleFinish} />
        )}
      </CardContent>
    </Card>
  );
}
