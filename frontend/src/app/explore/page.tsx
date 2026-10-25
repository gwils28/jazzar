"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import clsx from "clsx";
import { api, type Filters, type Hit } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { SourceCard } from "@/components/SourceCard";
import { ErrorBox, PageHeader, Spinner } from "@/components/ui";

const DOC_TYPES = ["review", "article", "poll", "interview", "wiki", "issue"];

export default function ExplorePage() {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<"hybrid" | "keyword">("hybrid");
  const [filters, setFilters] = useState<Filters>({ doc_types: [] });
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!q.trim()) return;
    setLoading(true); setError(null);
    try { setHits((await api.search(q, filters, mode, 20)).hits); } catch (err) { setError((err as Error).message); } finally { setLoading(false); }
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("explore.title")} subtitle={t("explore.subtitle")} />
      <form onSubmit={run} className="card p-3 flex flex-col gap-3">
        <div className="flex gap-2">
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("explore.placeholder")} />
          <button className="btn btn-primary" disabled={loading || !q.trim()}><Search size={14} /> {t("explore.search")}</button>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <div className="flex rounded-lg overflow-hidden border border-border-strong">
            {(["hybrid", "keyword"] as const).map((m) => <button type="button" key={m} onClick={() => setMode(m)} className={clsx("px-3 py-1.5", mode === m ? "bg-accent text-accent-fg" : "text-muted")}>{t(`explore.${m}`)}</button>)}
          </div>
          <label className="flex items-center gap-1.5">{t("ask.year_from")}<input type="number" className="input-sm w-24" value={filters.year_from ?? ""} onChange={(e) => setFilters({ ...filters, year_from: e.target.value ? Number(e.target.value) : null })} /></label>
          <label className="flex items-center gap-1.5">{t("ask.year_to")}<input type="number" className="input-sm w-24" value={filters.year_to ?? ""} onChange={(e) => setFilters({ ...filters, year_to: e.target.value ? Number(e.target.value) : null })} /></label>
          <div className="flex items-center gap-1.5 flex-wrap">
            {DOC_TYPES.map((d) => { const on = filters.doc_types?.includes(d); return <button type="button" key={d} onClick={() => setFilters({ ...filters, doc_types: on ? filters.doc_types!.filter((x) => x !== d) : [...(filters.doc_types ?? []), d] })} className={clsx("chip", on && "chip-accent")}>{d}</button>; })}
          </div>
        </div>
      </form>
      {loading && <Spinner />}
      {error && <ErrorBox message={error} />}
      {hits && !loading && (
        <>
          <div className="text-xs text-faint">{hits.length} {t("explore.results")}</div>
          {hits.length === 0 ? <p className="text-muted">{t("explore.none")}</p> : (
            <div className="grid md:grid-cols-2 gap-3">{hits.map((h, i) => <SourceCard key={h.chunk_id} hit={h} label={String(i + 1)} />)}</div>
          )}
        </>
      )}
    </div>
  );
}
