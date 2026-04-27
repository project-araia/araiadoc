"use client";

import { useRef, useState } from "react";
import { ToolCard } from "@/components/ToolCard";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function CrawlEpa() {
  const startRef = useRef<HTMLInputElement>(null);
  const stopRef = useRef<HTMLInputElement>(null);
  const termRef = useRef<HTMLInputElement>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const buildArgs = (): string[] | null => {
    setValidationError(null);
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

  return (
    <ToolCard
      title="Crawl EPA"
      description="Async crawl of EPA NEPIS pages and download OCR .txt files."
      tool="crawl-epa"
      buildArgs={buildArgs}
    >
      {({ disabled }) => (
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
      )}
    </ToolCard>
  );
}
