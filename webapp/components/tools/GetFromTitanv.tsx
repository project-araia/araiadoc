"use client";

import { useRef, useState } from "react";
import { ToolCard } from "@/components/ToolCard";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

export function GetFromTitanv() {
  const sourceRef = useRef<HTMLInputElement>(null);
  const outputDirRef = useRef<HTMLInputElement>(null);
  const [allTerms, setAllTerms] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const buildArgs = (): string[] | null => {
    setValidationError(null);
    const source = sourceRef.current?.value.trim() ?? "";
    const outputDir = outputDirRef.current?.value.trim() ?? "";

    // Either source OR all-terms flag must be provided
    if (!source && !allTerms) {
      setValidationError("Provide a source file path or enable All-terms search.");
      return null;
    }

    const args: string[] = [];
    if (source) args.push("--source", source);
    if (allTerms) args.push("--all-terms");
    if (outputDir) args.push("--output-dir", outputDir);
    return args;
  };

  return (
    <ToolCard
      title="Get from TitanV"
      description="Query TitanV Solr (S2ORC) by corpus ID file or run an all-terms cursor search."
      tool="get-from-titanv"
      buildArgs={buildArgs}
    >
      {({ disabled }) => (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor="titanv-source" className="text-xs">
              Source file (corpus IDs, optional if all-terms)
            </Label>
            <Input
              id="titanv-source"
              ref={sourceRef}
              placeholder="../data/OSTI_doc_ids.json"
              disabled={disabled || allTerms}
              className="h-8 text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="titanv-output" className="text-xs">Output dir (optional)</Label>
            <Input
              id="titanv-output"
              ref={outputDirRef}
              placeholder="../data/titanv_output/"
              disabled={disabled}
              className="h-8 text-xs"
            />
          </div>
          <div className="flex items-center gap-2 pt-4">
            <Switch
              id="titanv-all"
              checked={allTerms}
              onCheckedChange={setAllTerms}
              disabled={disabled}
            />
            <Label htmlFor="titanv-all" className="text-xs">
              All-terms search (-a)
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
