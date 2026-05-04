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
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { CATEGORIES, LARGE_RESULT_THRESHOLD } from "@/lib/titanvQueries";
import type { SearchResult } from "@/app/api/titanv/search/route";

export function TitanvSearch() {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isSearching, setIsSearching] = useState(false);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleSearch = async () => {
    setError(null);
    setResult(null);

    if (selected.size === 0) {
      setError("Select at least one category.");
      return;
    }

    setIsSearching(true);
    try {
      const params = new URLSearchParams({
        categories: Array.from(selected).join(","),
        rows: "20",
      });
      const res = await fetch(`/api/titanv/search?${params}`);
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error ?? `HTTP ${res.status}`);
      }
      setResult(data as SearchResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setIsSearching(false);
    }
  };

  const downloadUrl = result
    ? `/api/titanv/download?categories=${Array.from(selected).join(",")}`
    : null;

  const formatAuthors = (authors: string[]) => {
    if (authors.length === 0) return "—";
    if (authors.length <= 3) return authors.join(", ");
    return `${authors.slice(0, 3).join(", ")} +${authors.length - 3} more`;
  };

  return (
    <Card className="bg-card border-border">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle className="text-base font-semibold">TitanV Search</CardTitle>
            <CardDescription className="text-xs mt-1">
              Query the TitanV Solr (S2ORC) corpus by climate hazard category.
            </CardDescription>
          </div>
          <Badge variant="secondary" className="text-xs font-mono shrink-0">
            get-from-titanv
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Category checkboxes */}
        <div>
          <p className="text-xs text-muted-foreground mb-2">Select categories (OR-combined)</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-y-2 gap-x-4">
            {CATEGORIES.map((cat) => (
              <label
                key={cat.id}
                className="flex items-center gap-2 cursor-pointer select-none"
              >
                <input
                  type="checkbox"
                  checked={selected.has(cat.id)}
                  onChange={() => toggle(cat.id)}
                  disabled={isSearching}
                  className="size-4 rounded border border-input bg-transparent accent-primary cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                />
                <span className="text-xs leading-none">{cat.label}</span>
              </label>
            ))}
          </div>
        </div>

        {error && (
          <p className="text-xs text-red-400 border border-red-400/30 rounded px-2 py-1 bg-red-400/5">
            {error}
          </p>
        )}

        <Button
          onClick={handleSearch}
          disabled={isSearching || selected.size === 0}
          className="w-full"
          size="sm"
        >
          {isSearching ? "Searching..." : "Search"}
        </Button>

        {/* Results */}
        {result && (
          <div className="space-y-3">
            {/* Summary row */}
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <span className="text-xs text-muted-foreground">
                <span className="text-foreground font-medium">
                  {result.numFound.toLocaleString()}
                </span>{" "}
                documents found &mdash; showing first {result.docs.length}
              </span>
              {downloadUrl && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs gap-1.5 border-green-500/30 hover:border-green-500/50 bg-green-500/5 text-green-400"
                  onClick={() => window.open(downloadUrl, "_blank")}
                >
                  Download all (.jsonl)
                </Button>
              )}
            </div>

            {/* Large result warning */}
            {result.largeResultWarning && (
              <p className="text-xs text-yellow-400 border border-yellow-400/30 rounded px-2 py-1 bg-yellow-400/5">
                Warning: this query matches more than{" "}
                {LARGE_RESULT_THRESHOLD.toLocaleString()} documents. The full
                download may be very large and take a long time.
              </p>
            )}

            {/* Results table */}
            <ScrollArea className="h-96 w-full rounded-md border border-border">
              <div className="divide-y divide-border">
                {result.docs.map((doc, i) => (
                  <div key={doc.corpus_id ?? i} className="px-3 py-3 space-y-1">
                    {/* Title + year */}
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-xs font-medium leading-snug flex-1">
                        {doc.title}
                      </p>
                      {doc.year && (
                        <span className="text-xs text-muted-foreground shrink-0">
                          {doc.year}
                        </span>
                      )}
                    </div>

                    {/* Authors */}
                    <p className="text-xs text-muted-foreground">
                      {formatAuthors(doc.authors)}
                    </p>

                    {/* Venue */}
                    {doc.venue && (
                      <p className="text-xs text-muted-foreground italic">
                        {doc.venue}
                      </p>
                    )}

                    {/* Abstract */}
                    {doc.abstract && (
                      <p className="text-xs text-muted-foreground leading-relaxed line-clamp-3">
                        {doc.abstract}
                      </p>
                    )}

                    {/* DOI */}
                    {doc.doi && (
                      <p className="text-xs">
                        <span className="text-muted-foreground">DOI: </span>
                        <a
                          href={`https://doi.org/${doc.doi}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-400 hover:underline break-all"
                        >
                          {doc.doi}
                        </a>
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
