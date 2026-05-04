import { NextRequest, NextResponse } from "next/server";
import { buildQuery, TITANV_SELECT_URL, LARGE_RESULT_THRESHOLD } from "@/lib/titanvQueries";

export const runtime = "nodejs";

export interface SolrDoc {
  corpus_id?: number[];
  title?: string[];
  abstract?: string[];
  authors?: string[];
  year?: number[];
  doi?: string[];
  venue?: string[];
}

export interface SearchResult {
  numFound: number;
  largeResultWarning: boolean;
  docs: {
    corpus_id: number | null;
    title: string;
    abstract: string;
    authors: string[];
    year: number | null;
    doi: string;
    venue: string;
  }[];
}

/**
 * GET /api/titanv/search?categories=heat,flooding&rows=20&start=0
 */
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const categoriesParam = searchParams.get("categories") ?? "";
  const relevance = searchParams.get("relevance") ?? "default";
  const rows = Math.min(parseInt(searchParams.get("rows") ?? "20", 10), 100);
  const start = parseInt(searchParams.get("start") ?? "0", 10);

  const categoryIds = categoriesParam
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const query = buildQuery(categoryIds, relevance);
  if (!query) {
    return NextResponse.json({ error: "No valid categories selected" }, { status: 400 });
  }

  const params = new URLSearchParams({
    "df": "paragraph",
    "indent": "true",
    "q.op": "OR",
    "q": query,
    "rows": String(rows),
    "start": String(start),
    "fl": "corpus_id,title,abstract,authors,year,doi,venue",
    "useParams": "",
  });

  let solrRes: Response;
  try {
    solrRes = await fetch(`${TITANV_SELECT_URL}?${params}`, {
      signal: AbortSignal.timeout(30_000),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: `Solr unreachable: ${msg}` }, { status: 502 });
  }

  if (!solrRes.ok) {
    return NextResponse.json(
      { error: `Solr returned HTTP ${solrRes.status}` },
      { status: 502 }
    );
  }

  const payload = await solrRes.json();
  const response = payload?.response;
  if (!response) {
    return NextResponse.json({ error: "Unexpected Solr response shape" }, { status: 502 });
  }

  const numFound: number = response.numFound ?? 0;

  const docs = (response.docs as SolrDoc[]).map((doc) => ({
    corpus_id: doc.corpus_id?.[0] ?? null,
    title: doc.title?.[0] ?? "(no title)",
    abstract: doc.abstract?.[0] ?? "",
    authors: doc.authors ?? [],
    year: doc.year?.[0] ?? null,
    doi: doc.doi?.[0] ?? "",
    venue: doc.venue?.[0] ?? "",
  }));

  const result: SearchResult = {
    numFound,
    largeResultWarning: numFound > LARGE_RESULT_THRESHOLD,
    docs,
  };

  return NextResponse.json(result);
}
