import { NextRequest } from "next/server";
import { buildQuery, TITANV_SELECT_URL } from "@/lib/titanvQueries";

export const runtime = "nodejs";

const ROWS_PER_PAGE = 1000;

/**
 * GET /api/titanv/download?categories=heat,flooding
 *
 * Streams a .jsonl file (one JSON object per line) containing all matching
 * Solr documents, using cursor-based pagination. The browser receives it as
 * a file download.
 */
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const categoriesParam = searchParams.get("categories") ?? "";
  const relevance = searchParams.get("relevance") ?? "default";

  const categoryIds = categoriesParam
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const query = buildQuery(categoryIds, relevance);
  if (!query) {
    return new Response("No valid categories selected", { status: 400 });
  }

  const filename = `titanv_${categoryIds.join("_")}.jsonl`;

  const stream = new ReadableStream({
    async start(controller) {
      const enc = new TextEncoder();

      let cursorMark = "*";
      let pagesFetched = 0;

      try {
        while (true) {
          const params = new URLSearchParams({
            df: "paragraph",
            "q.op": "OR",
            q: query,
            rows: String(ROWS_PER_PAGE),
            sort: "id asc",
            cursorMark,
            fl: "corpus_id,title,abstract,authors,year,doi,venue",
            useParams: "",
          });

          let res: Response;
          try {
            res = await fetch(`${TITANV_SELECT_URL}?${params}`, {
              signal: AbortSignal.timeout(120_000),
            });
          } catch (err) {
            const msg = err instanceof Error ? err.message : "unknown";
            controller.error(new Error(`Solr fetch failed: ${msg}`));
            return;
          }

          if (!res.ok) {
            controller.error(new Error(`Solr HTTP ${res.status}`));
            return;
          }

          const payload = await res.json();
          const docs: unknown[] = payload?.response?.docs ?? [];
          const nextCursorMark: string = payload?.nextCursorMark ?? cursorMark;

          for (const doc of docs) {
            controller.enqueue(enc.encode(JSON.stringify(doc) + "\n"));
          }

          pagesFetched++;

          if (!docs.length || nextCursorMark === cursorMark) break;
          cursorMark = nextCursorMark;
        }

        controller.close();
      } catch (err) {
        controller.error(err);
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "application/x-ndjson",
      "Content-Disposition": `attachment; filename="${filename}"`,
      "Cache-Control": "no-cache",
    },
  });
}
