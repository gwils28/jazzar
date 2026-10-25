"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ArrowLeft, Download } from "lucide-react";
import { api, type DossierDetail } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Markdown } from "@/components/Markdown";
import { SourceCard } from "@/components/SourceCard";
import { ErrorBox, Spinner, fmtUsd } from "@/components/ui";
import { StatusChip } from "../page";

export default function DossierPage() {
  return <Suspense fallback={<Spinner />}><DossierPageInner /></Suspense>;
}

function DossierPageInner() {
  const { id } = useParams<{ id: string }>();
  const { t, locale } = useI18n();
  const [d, setD] = useState<DossierDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.dossier(id).then((x) => { if (alive) setD(x); }).catch((e) => setError(e.message));
    load();
    const tick = setInterval(() => { if (d && ["done", "failed"].includes(d.status)) return; load(); }, 4000);
    return () => { alive = false; clearInterval(tick); };
  }, [id, d?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorBox message={error} />;
  if (!d) return <Spinner />;

  const download = () => {
    const blob = new Blob([d.markdown ?? ""], { type: "text/markdown" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${(d.title ?? "dossier").replace(/[^\w\-]+/g, "_")}.md`; a.click();
  };
  const onCite = (ref: string) => { setActive(ref); document.getElementById(`src-${ref}`)?.scrollIntoView({ behavior: "smooth", block: "center" }); };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/dossiers" className="btn btn-ghost !px-3"><ArrowLeft size={14} /> {t("library.back")}</Link>
        <StatusChip status={d.status} />
        <span className="text-xs text-faint">{t("dossiers.cost")} {fmtUsd(d.cost_usd)} · {new Date(d.created_at).toLocaleString(locale)}</span>
        {d.markdown && <button onClick={download} className="btn btn-ghost ml-auto"><Download size={14} /> {t("dossiers.export")}</button>}
      </div>
      {d.error && <ErrorBox message={d.error} />}
      <div className="grid lg:grid-cols-[1fr_340px] gap-6">
        <article className="card p-5 md:p-8 min-w-0">
          {d.markdown ? <Markdown text={d.markdown} onCite={onCite} /> : (
            <div className="flex flex-col gap-4">
              <Spinner label={t(`dossiers.status.${d.status}`)} />
              {d.plan?.sections && (
                <div>
                  <div className="text-xs uppercase tracking-wide text-faint mb-2">{t("dossiers.plan")} — {d.plan.title}</div>
                  <ol className="list-decimal ml-5 text-sm text-muted flex flex-col gap-1">{d.plan.sections.map((s) => <li key={s.heading}><span className="text-fg">{s.heading}</span> — {s.goal}</li>)}</ol>
                </div>
              )}
            </div>
          )}
        </article>
        <aside className="flex flex-col gap-4 lg:sticky lg:top-6 lg:max-h-[85vh] lg:overflow-auto">
          <section className="card p-3">
            <div className="text-xs uppercase tracking-wide text-faint mb-2">{t("dossiers.steps")}</div>
            <ol className="text-xs flex flex-col gap-1.5 mono">
              {d.steps.map((s, i) => (
                <li key={i} className="flex gap-2 text-muted"><span className="text-accent">▸</span><span className="truncate">{String(s.step)} {s.section ? `· ${String(s.section)}` : ""}{s.tool_calls != null ? ` · ${String(s.tool_calls)} tool calls` : ""}{s.words != null ? ` · ${String(s.words)} words` : ""}{s.confidence != null ? ` · conf ${Number(s.confidence).toFixed(2)}` : ""}</span></li>
              ))}
            </ol>
          </section>
          {d.citations?.length > 0 && (
            <section className="flex flex-col gap-2">
              <div className="text-xs uppercase tracking-wide text-faint px-1">{t("dossiers.sources")} · {d.citations.length}</div>
              {d.citations.map((c) => <SourceCard key={c.id} hit={c} label={c.id} highlighted={active === c.id} compact />)}
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
