"use client";

import { useRef, useState } from "react";
import { ToolCard } from "@/components/ToolCard";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function CrawlOsti() {
  const startYearRef = useRef<HTMLInputElement>(null);
  const termRef = useRef<HTMLInputElement>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const buildArgs = (): string[] | null => {
    setValidationError(null);
    const year = startYearRef.current?.value.trim() ?? "";
    const term = termRef.current?.value.trim() ?? "";

    if (!year || isNaN(Number(year)) || Number(year) < 1900 || Number(year) > 2100) {
      setValidationError("Start year must be a valid 4-digit year.");
      return null;
    }

    const args = [year];
    if (term) args.push("--search-term", term);
    return args;
  };

  return (
    <ToolCard
      title="Crawl OSTI"
      description="Async crawl of OSTI and download PDFs via the OSTI API."
      tool="crawl-osti"
      buildArgs={buildArgs}
    >
      {({ disabled }) => (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="osti-year" className="text-xs">Start year</Label>
            <Input
              id="osti-year"
              ref={startYearRef}
              type="number"
              placeholder="2020"
              disabled={disabled}
              className="h-8 text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="osti-term" className="text-xs">Search term (optional)</Label>
            <Input
              id="osti-term"
              ref={termRef}
              placeholder="wildfire"
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
