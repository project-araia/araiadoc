"use client";

import { useRef, useState } from "react";
import { ToolCard } from "@/components/ToolCard";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";

export function CrawlEpa() {
  const startRef = useRef<HTMLInputElement>(null);
  const stopRef = useRef<HTMLInputElement>(null);
  const termRef = useRef<HTMLInputElement>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [zipUrl, setZipUrl] = useState<string | null>(null);

  const buildArgs = (): string[] | null => {
    setValidationError(null);
    setZipUrl(null);
    const start = startRef.current?.value.trim() ?? "";
    const stop = stopRef.current?.value.trim() ?? "";
    const term = termRef.current?.value.trim() ?? "";

    if (!start || isNaN(Number(start))) {
      setValidationError("Start index must be a number.");
      return null;
    }
    if (!stop || isNaN(Number(stop))) {
      setValidationError("Stop index must be a number.");
      return null;
    }

    const args = [start, stop];
    if (term) args.push("--search-term", term);
    return args;
  };

  const handleFinish = async (exitCode: number, jobId: string) => {
    if (exitCode !== 0) return;

    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) return;
      const job = await res.json();

      // Look for the line: "Output directory: /path/to/dir"
      const outputLine = job.lines.find((l: string) => l.includes("Output directory:"));
      if (outputLine) {
        const match = outputLine.match(/Output directory: (.*)/);
        if (match && match[1]) {
          const dirPath = match[1].trim();
          setZipUrl(`/api/download/zip?dir=${encodeURIComponent(dirPath)}`);
        }
      }
    } catch (err) {
      console.error("Failed to fetch job info for zip download", err);
    }
  };

  return (
    <ToolCard
      title="Crawl EPA"
      description="Async crawl of EPA NEPIS pages and download OCR .txt files."
      tool="crawl-epa"
      buildArgs={buildArgs}
      onFinish={handleFinish}
    >
      {({ disabled }) => (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label htmlFor="epa-start" className="text-xs">Start index</Label>
              <Input
                id="epa-start"
                ref={startRef}
                type="number"
                placeholder="0"
                disabled={disabled}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="epa-stop" className="text-xs">Stop index</Label>
              <Input
                id="epa-stop"
                ref={stopRef}
                type="number"
                placeholder="100"
                disabled={disabled}
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="epa-term" className="text-xs">Search term (optional)</Label>
              <Input
                id="epa-term"
                ref={termRef}
                placeholder="flooding"
                disabled={disabled}
                className="h-8 text-xs"
              />
            </div>
            {validationError && (
              <p className="col-span-full text-xs text-red-400">{validationError}</p>
            )}
          </div>

          {zipUrl && (
            <div className="pt-2 animate-in fade-in slide-in-from-top-2 duration-300">
              <Button
                variant="outline"
                size="sm"
                className="w-full gap-2 text-xs h-8 border-green-500/30 hover:border-green-500/50 bg-green-500/5 text-green-400"
                onClick={() => window.open(zipUrl, "_blank")}
              >
                <Download className="size-3" />
                Download results (.zip)
              </Button>
            </div>
          )}
        </div>
      )}
    </ToolCard>
  );
}
