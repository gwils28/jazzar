export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100";

export type Filters = { year_from?: number | null; year_to?: number | null; doc_types?: string[]; authors?: string[]; source_kinds?: string[] };

export type Hit = {
  n?: number; chunk_id: string; document_id: string; title: string; doc_type: string; text: string; score: number;
  author?: string | null; published_on?: string | null; year?: number | null; issue?: string | null; page?: number | null;
  source_kind?: string | null; source_name?: string | null; url?: string | null; file_path?: string | null;
};

export type AskEvent =
  | { type: "route"; trace_id: string; route: string; via_llm: boolean; filters: Filters; keywords: string[]; rationale: string }
  | { type: "sources"; hits: Hit[] }
  | { type: "cached"; similarity: number; cached_question: string }
  | { type: "token"; text: string }
  | { type: "notice"; text: string }
  | { type: "redirect"; to: string; trace_id: string }
  | { type: "done"; trace_id: string; route: string; citations: Hit[]; cost_usd: number; latency_ms: number; cached: boolean; model?: string }
  | { type: "error"; message: string };

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}/api${path}`, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) } });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => json<Health>("/health"),
  stats: () => json<Stats>("/stats"),
  search: (query: string, filters: Filters, mode: "hybrid" | "keyword", top_k = 12) => json<{ hits: Hit[] }>("/search", { method: "POST", body: JSON.stringify({ query, filters, mode, top_k }) }),
  feedback: (trace_id: string, score: 1 | -1, comment?: string) => json<{ ok: boolean }>("/feedback", { method: "POST", body: JSON.stringify({ trace_id, score, comment }) }),
  documents: (params: Record<string, string | number | undefined>) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
    return json<DocSummary[]>(`/documents?${q}`);
  },
  document: (id: string) => json<DocDetail>(`/documents/${id}`),
  dossiers: () => json<DossierSummary[]>("/dossiers"),
  dossier: (id: string) => json<DossierDetail>(`/dossiers/${id}`),
  createDossier: (brief: string, lang: string) => json<{ id: string; status: string }>("/dossiers", { method: "POST", body: JSON.stringify({ brief, lang }) }),
  bi: (question: string, lang: string) => json<BIResult>("/bi/analyze", { method: "POST", body: JSON.stringify({ question, lang }) }),
  evals: () => json<EvalSummary[]>("/evals"),
  eval: (id: string) => json<EvalDetail>(`/evals/${id}`),
  runEval: () => json<{ status: string }>("/evals/run", { method: "POST", body: "{}" }),
  recentQueries: () => json<RecentQuery[]>("/queries"),
  pdfUrl: (docId: string, page?: number | null) => `${API_URL}/api/documents/${docId}/pdf${page ? `#page=${page}` : ""}`,
};

/** POST /ask en SSE : lit le flux et appelle onEvent pour chaque événement. */
export async function askStream(body: { question: string; lang?: string; filters?: Filters; use_cache?: boolean }, onEvent: (e: AskEvent) => void, signal?: AbortSignal) {
  const res = await fetch(`${API_URL}/api/ask`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n"); // sse-starlette émet des CRLF
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLines = frame.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart());
      if (!dataLines.length) continue;
      try { onEvent(JSON.parse(dataLines.join("\n")) as AskEvent); } catch {}
    }
  }
}

export type Health = { status: string; llm_available: boolean; models: { large: string; small: string }; embedding_model: string; text_backend: string; redis: boolean; documents: number; chunks: number };
export type Stats = {
  corpus: { sources: { kind: string; name: string; documents: number }[]; doc_types: Record<string, number>; year_min: number | null; year_max: number | null; reviews: number; chunks: number };
  llm: { total_cost_usd: number; calls: number; by_purpose: { purpose: string; calls: number; cost_usd: number; avg_latency_ms: number; cache_read_tokens: number; input_tokens: number }[] };
  queries: { total: number; avg_latency_ms: number; p95_latency_ms: number; cached: number; thumbs_up: number; thumbs_down: number; routes: Record<string, number> };
};
export type DocSummary = { id: string; title: string; author: string | null; doc_type: string; published_on: string | null; year: number | null; issue: string | null; language: string; url: string | null; source_kind: string; source_name: string; chunks: number; page_count?: number | null };
export type DocDetail = DocSummary & { file_path: string | null; meta: Record<string, unknown>; has_pdf: boolean; chunks: { id: string; ordinal: number; page: number | null; text: string }[]; reviews: { album_title: string; artist: string; label: string | null; release_year: number | null; rating: number | null; genre: string | null }[] };
export type DossierSummary = { id: string; created_at: string; updated_at: string; brief: string; lang: string; status: string; title: string | null; cost_usd: number; error: string | null; n_citations: number; steps: Record<string, unknown>[] };
export type DossierDetail = DossierSummary & { plan: { title?: string; audience?: string; sections?: { heading: string; goal: string; research_questions: string[] }[] }; markdown: string | null; citations: (Hit & { id: string })[] };
export type BIResult = { trace_id: string; question: string; plan: { feasible: boolean; explanation: string; caveats: string[]; chart: { type: string; title: string } }; sql: string | null; columns: string[]; rows: unknown[][]; figure: { data: Record<string, unknown>[]; layout: Record<string, unknown> } | null; insight: string; cost_usd: number; latency_ms: number };
export type EvalSummary = { id: string; created_at: string; system_version: string; golden_set: string; aggregate: Record<string, number | Record<string, number>>; passed_gates: boolean; cost_usd: number };
export type EvalDetail = EvalSummary & { per_case: Record<string, unknown>[] };
export type RecentQuery = { trace_id: string; question: string; route: string | null; cached: boolean; latency_ms: number | null; cost_usd: number; feedback: number | null; created_at: string; lang: string };
