"use client";

import { CrawlEpa } from "@/components/tools/CrawlEpa";
import { CrawlOsti } from "@/components/tools/CrawlOsti";
import { CompleteSemanticScholar } from "@/components/tools/CompleteSemanticScholar";
import { TitanvSearch } from "@/components/tools/TitanvSearch";

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Pipeline Tools</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Configure and run araiadoc tools. Logs stream in real time below each job.
        </p>
      </div>

      <div className="grid gap-4">
        <CrawlEpa />
        <CrawlOsti />
        <CompleteSemanticScholar />
        <TitanvSearch />
      </div>
    </div>
  );
}
