"use client";

import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { BarChart3, Zap } from "lucide-react";
import { api, type BIResult } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ErrorBox, PageHeader, Spinner, fmtMs, fmtUsd } from "@/components/ui";

const Plot = dynamic(() => import("@/components/Plot"), { ssr: false, loading: () => <Spinner /> });

export default function InsightsPage() {
  return <Suspense fallback={<Spinner />}><Insights /></Suspense>;
}

function Insights() {
  const { t, tl, locale } = useI18n();
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [res, setRes] = useState<BIResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (question: string) => {
    if (!question.trim()) return;
    setLoading(true); setError(null); setRes(null);
    try { setRes(await api.bi(question, locale)); } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  };
  useEffect(() => { const initial = params.get("q"); if (initial) run(initial); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("insights.title")} subtitle={t("insights.subtitle")} />
      <form onSubmit={(e) => { e.preventDefault(); run(q); }} className="card p-3 flex gap-2">
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("insights.placeholder")} />
        <button className="btn btn-primary" disabled={loading || !q.trim()}><BarChart3 size={14} /> {t("insights.analyze")}</button>
      </form>
      {!res && !loading && (
        <div className="grid sm:grid-cols-2 gap-3">
          {tl("insights.examples").map((ex) => <button key={ex} onClick={() => { setQ(ex); run(ex); }} className="card p-4 text-left text-sm text-muted hover:text-fg transition"><Zap size={14} className="inline mr-2 text-accent" />{ex}</button>)}
        </div>
      )}
      {loading && <Spinner label="Text-to-SQL…" />}
      {error && <ErrorBox message={error} />}
      {res && (
        <div className="flex flex-col gap-4">
          {!res.plan.feasible && <ErrorBox message={`${t("insights.infeasible")} ${res.plan.explanation}`} />}
          {res.figure && <div className="card p-3"><Plot figure={res.figure} /></div>}
          <div className="grid lg:grid-cols-[1fr_1fr] gap-4">
            <section className="card p-4">
              <div className="text-xs uppercase tracking-wide text-faint mb-2">{t("insights.insight")}</div>
              <p className="leading-relaxed">{res.insight}</p>
              {res.plan.caveats?.length > 0 && (<><div className="text-xs uppercase tracking-wide text-faint mt-4 mb-1">{t("insights.caveats")}</div><ul className="text-sm text-muted list-disc ml-5">{res.plan.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul></>)}
              <div className="text-xs text-faint mt-4 flex gap-3"><span>{fmtMs(res.latency_ms)}</span><span>{fmtUsd(res.cost_usd)}</span></div>
            </section>
            {res.sql && (
              <section className="card p-4 min-w-0">
                <div className="text-xs uppercase tracking-wide text-faint mb-2">{t("insights.sql")}</div>
                <pre className="mono text-xs whitespace-pre-wrap break-words text-muted">{res.sql}</pre>
                <p className="text-xs text-faint mt-2">{res.plan.explanation}</p>
              </section>
            )}
          </div>
          {res.rows.length > 0 && (
            <section className="card p-0 overflow-auto max-h-[420px]">
              <div className="text-xs uppercase tracking-wide text-faint px-4 pt-3">{t("insights.data")} · {res.rows.length} {t("insights.rows")}</div>
              <table className="w-full text-sm mt-2">
                <thead className="sticky top-0" style={{ background: "var(--bg-elev)" }}><tr>{res.columns.map((c) => <th key={c} className="text-left px-4 py-2 border-b border-border font-medium text-muted mono text-xs">{c}</th>)}</tr></thead>
                <tbody>{res.rows.map((r, i) => <tr key={i} className="odd:bg-elev-2/40">{r.map((v, j) => <td key={j} className="px-4 py-1.5 border-b border-border">{typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(2)) : String(v ?? "")}</td>)}</tr>)}</tbody>
              </table>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
