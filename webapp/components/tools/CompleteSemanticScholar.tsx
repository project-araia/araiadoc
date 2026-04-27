"use client";

import { useRef, useState } from "react";
import { ToolCard } from "@/components/ToolCard";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export function CompleteSemanticScholar() {
  const inputFileRef = useRef<HTMLInputElement>(null);
  const nProcRef = useRef<HTMLInputElement>(null);
  const [inputFormat, setInputFormat] = useState("csv");
  const [outputFormat, setOutputFormat] = useState("json");
  const [validationError, setValidationError] = useState<string | null>(null);

  const buildArgs = (): string[] | null => {
    setValidationError(null);
    const inputFile = inputFileRef.current?.value.trim() ?? "";
    const nProc = nProcRef.current?.value.trim() ?? "";

    if (!inputFile) {
      setValidationError("Input file path is required.");
      return null;
    }

    const args = [inputFile, "--input-format", inputFormat, "--output-format", outputFormat];
    if (nProc && !isNaN(Number(nProc))) {
      args.push("--nproc", nProc);
    }
    return args;
  };

  return (
    <ToolCard
      title="Complete Semantic Scholar"
      description="Download PDFs or metadata from Semantic Scholar by corpus ID."
      tool="complete-semantic-scholar"
      buildArgs={buildArgs}
    >
      {({ disabled }) => (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor="ss-input" className="text-xs">Input file path</Label>
            <Input
              id="ss-input"
              ref={inputFileRef}
              placeholder="../data/climate_ID_600k_label.csv"
              disabled={disabled}
              className="h-8 text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ss-input-format" className="text-xs">Input format</Label>
            <Select
              value={inputFormat}
              onValueChange={(v) => { if (v !== null) setInputFormat(v); }}
              disabled={disabled}
            >
              <SelectTrigger id="ss-input-format" className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="csv">csv</SelectItem>
                <SelectItem value="json">json</SelectItem>
                <SelectItem value="txt">txt</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="ss-output-format" className="text-xs">Output format</Label>
            <Select
              value={outputFormat}
              onValueChange={(v) => { if (v !== null) setOutputFormat(v); }}
              disabled={disabled}
            >
              <SelectTrigger id="ss-output-format" className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="json">json</SelectItem>
                <SelectItem value="pdf">pdf</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="ss-nproc" className="text-xs">Workers (optional)</Label>
            <Input
              id="ss-nproc"
              ref={nProcRef}
              type="number"
              placeholder="4"
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
