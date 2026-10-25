"use client";

import { useEffect, useState } from "react";
import { Play } from "lucide-react";
import clsx from "clsx";
import { api, type EvalSummary, type RecentQuery, type Stats } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ErrorBox, PageHeader, Spinner, Stat, fmtMs, fmtUsd } from "@/components/ui";

export default function ObservatoryPage() {
  const { t, locale } = useI18n();
  const [stats, setStats] = useState<Stats | null>(null);
  const [evals, setEvals] = useState<EvalSummary[] | null>(null);
  const [recent, setRecent] = useState<RecentQuery[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);

  const load = () => Promise.all([api.stats().then(setStats), api.evals().then(setEvals), api.recentQueries().then(setRecent)]).catch((e) => setError(e.message));
  useEffect(() => { load(); const id = setInterval(load, 10000); return () => clearInterval(id); }, []);

  const runEval = async () => { setLaunching(true); try { await api.runEval(); } catch (e) { setError((e as Error).message); } finally { setLaunching(false); } };

  if (error) return <ErrorBox message={error} />;
  if (!stats) return <Spinner />;
  const cacheRate = stats.queries.total ? Math.round((100 * stats.queries.cached) / stats.queries.total) : 0;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("observatory.title")} subtitle={t("observatory.subtitle")} right={<button onClick={runEval} disabled={launching} className="btn btn-primary"><Play size={14} /> {t("observatory.run_eval")}</button>} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label={t("observatory.p95")} value={fmtMs(stats.queries.p95_latency_ms)} hint={`${t("observatory.avg")} ${fmtMs(stats.queries.avg_latency_ms)}`} />
        <Stat label={t("observatory.cost")} value={fmtUsd(stats.llm.total_cost_usd)} hint={`${stats.llm.calls} ${t("observatory.calls")}`} />
        <Stat label={t("observatory.cached")} value={`${cacheRate}%`} hint={`${stats.queries.cached} / ${stats.queries.total}`} />
        <Stat label={t("observatory.feedback")} value={<span><span className="text-ok">👍 {stats.queries.thumbs_up}</span> <span className="text-faint">/</span> <span style={{ color: "#f0b5b5" }}>👎 {stats.queries.thumbs_down}</span></span>} />
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <section className="card p-4">
          <div className="text-xs uppercase tracking-wide text-faint mb-3">{t("observatory.queries")} — routes</div>
          <div className="flex flex-col gap-2">
            {Object.entries(stats.queries.routes).sort((a, b) => b[1] - a[1]).map(([r, n]) => (
              <div key={r} className="flex items-center gap-3 text-sm">
                <span className="w-36 mono text-xs text-muted truncate">{r}</span>
                <div className="flex-1 h-2 rounded-full bg-elev-2 overflow-hidden"><div className="h-full rounded-full" style={{ width: `${(100 * n) / Math.max(1, stats.queries.total)}%`, background: "var(--accent)" }} /></div>
                <span className="w-8 text-right mono text-xs">{n}</span>
              </div>
            ))}
          </div>
        </section>
        <section className="card p-4 overflow-auto">
          <div className="text-xs uppercase tracking-wide text-faint mb-3">{t("observatory.llm")}</div>
          <table className="w-full text-xs">
            <thead><tr className="text-left text-faint"><th className="py-1">{t("observatory.purpose")}</th><th className="text-right">{t("observatory.calls")}</th><th className="text-right">$</th><th className="text-right">ms</th><th className="text-right">cache</th></tr></thead>
            <tbody>{stats.llm.by_purpose.map((p) => (
              <tr key={p.purpose} className="border-t border-border"><td className="py-1.5 mono">{p.purpose}</td><td className="text-right">{p.calls}</td><td className="text-right">{p.cost_usd.toFixed(4)}</td><td className="text-right">{p.avg_latency_ms}</td><td className="text-right text-muted">{p.input_tokens ? Math.round((100 * p.cache_read_tokens) / (p.cache_read_tokens + p.input_tokens)) : 0}%</td></tr>
            ))}</tbody>
          </table>
        </section>
      </div>

      <section className="card p-4">
        <div className="text-xs uppercase tracking-wide text-faint mb-3">{t("observatory.evals")}</div>
        {!evals || evals.length === 0 ? <p className="text-sm text-muted">{t("observatory.no_eval")}</p> : (
          <div className="flex flex-col gap-2">
            {evals.map((e) => {
              const a = e.aggregate as Record<string, number>;
              return (
                <div key={e.id} className="card-2 p-3 flex flex-wrap items-center gap-3 text-sm">
                  <span className={clsx("chip", e.passed_gates ? "chip-ok" : "chip-danger")}>{e.passed_gates ? t("observatory.gates_ok") : t("observatory.gates_ko")}</span>
                  <span className="text-xs text-faint">{new Date(e.created_at).toLocaleString(locale)}</span>
                  <span className="mono text-xs text-muted truncate max-w-xs">{e.system_version}</span>
                  <div className="ml-auto flex gap-3 mono text-xs">
                    <Metric label="pass" v={a.pass_rate} /><Metric label="traps" v={a.refusal_trap_pass_rate} /><Metric label="cite" v={a.citation_coverage} /><Metric label="faith" v={a.faithfulness_factual} /><Metric label="R@k" v={a.retrieval_passk} />
                    <span className="text-faint">{fmtUsd(e.cost_usd)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="card p-4 overflow-auto">
        <div className="text-xs uppercase tracking-wide text-faint mb-3">{t("observatory.recent")}</div>
        <table className="w-full text-xs">
          <tbody>{(recent ?? []).map((r) => (
            <tr key={r.trace_id} className="border-t border-border"><td className="py-1.5 pr-3 max-w-md truncate">{r.question}</td><td className="mono text-muted pr-3">{r.route}</td><td className="text-right pr-3">{fmtMs(r.latency_ms)}</td><td className="text-right pr-3">{fmtUsd(r.cost_usd)}</td><td>{r.cached ? "⚡" : ""}{r.feedback === 1 ? "👍" : r.feedback === -1 ? "👎" : ""}</td></tr>
          ))}</tbody>
        </table>
      </section>
    </div>
  );
}

function Metric({ label, v }: { label: string; v?: number }) {
  if (v == null) return null;
  return <span><span className="text-faint">{label}</span> <span className={v >= 0.95 ? "text-ok" : v >= 0.8 ? "text-accent" : ""} style={v < 0.8 ? { color: "#f0b5b5" } : undefined}>{(v * 100).toFixed(0)}%</span></span>;
}
