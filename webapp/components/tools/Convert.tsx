"use client";

import { useRef, useState } from "react";
import { ToolCard } from "@/components/ToolCard";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

export function Convert() {
  const sourceRef = useRef<HTMLInputElement>(null);
  const outputDirRef = useRef<HTMLInputElement>(null);
  const grobidUrlRef = useRef<HTMLInputElement>(null);
  const [interactive, setInteractive] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const buildArgs = (): string[] | null => {
    setValidationError(null);
    const source = sourceRef.current?.value.trim() ?? "";
    const outputDir = outputDirRef.current?.value.trim() ?? "";
    const grobidUrl = grobidUrlRef.current?.value.trim() ?? "";

    if (!source) {
      setValidationError("Source path is required.");
      return null;
    }

    const args = [source];
    if (interactive) args.push("--interactive");
    if (outputDir) args.push("--output-dir", outputDir);
    if (grobidUrl) args.push("--grobid-url", grobidUrl);
    return args;
  };

  return (
    <ToolCard
      title="Convert"
      description="Convert PDFs to structured JSON using Grobid or OpenParse."
      tool="convert"
      buildArgs={buildArgs}
    >
      {({ disabled }) => (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor="convert-source" className="text-xs">Source path</Label>
            <Input
              id="convert-source"
              ref={sourceRef}
              placeholder="../data/osti_pdfs/"
              disabled={disabled}
              className="h-8 text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="convert-output" className="text-xs">Output dir (optional)</Label>
            <Input
              id="convert-output"
              ref={outputDirRef}
              placeholder="../data/converted/"
              disabled={disabled}
              className="h-8 text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="convert-grobid" className="text-xs">Grobid URL (optional)</Label>
            <Input
              id="convert-grobid"
              ref={grobidUrlRef}
              placeholder="http://localhost:8070"
              disabled={disabled}
              className="h-8 text-xs"
            />
          </div>
          <div className="flex items-center gap-2 pt-1">
            <Switch
              id="convert-interactive"
              checked={interactive}
              onCheckedChange={setInteractive}
              disabled={disabled}
            />
            <Label htmlFor="convert-interactive" className="text-xs">
              Interactive mode (-i)
            </Label>
          </div>
          {validationError && (
            <p className="col-span-full text-xs text-red-400">{validationError}</p>
          )}
        </div>
      )}
    </ToolCard>
  );
}
