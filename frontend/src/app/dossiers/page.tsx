"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FileText, Sparkles } from "lucide-react";
import clsx from "clsx";
import { api, type DossierSummary } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ErrorBox, PageHeader, Spinner, fmtUsd } from "@/components/ui";

export function StatusChip({ status }: { status: string }) {
  const { t } = useI18n();
  const cls = status === "done" ? "chip-ok" : status === "failed" ? "chip-danger" : "chip-accent";
  const live = !["done", "failed"].includes(status);
  return <span className={clsx("chip", cls)}>{live && <span className="dot" />}{t(`dossiers.status.${status}`)}</span>;
}

export default function DossiersPage() {
  const { t, locale } = useI18n();
  const [list, setList] = useState<DossierSummary[] | null>(null);
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.dossiers().then(setList).catch((e) => setError(e.message));
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!brief.trim()) return;
    setBusy(true); setError(null);
    try { await api.createDossier(brief.trim(), locale); setBrief(""); await load(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("dossiers.title")} subtitle={t("dossiers.subtitle")} />
      <form onSubmit={create} className="card p-4 flex flex-col gap-3">
        <label className="text-sm text-muted">{t("dossiers.brief")}</label>
        <textarea className="input resize-y" rows={3} value={brief} onChange={(e) => setBrief(e.target.value)} placeholder={t("dossiers.placeholder")} />
        <div className="flex justify-end"><button className="btn btn-primary" disabled={busy || brief.trim().length < 10}><Sparkles size={14} /> {t("dossiers.create")}</button></div>
      </form>
      {error && <ErrorBox message={error} />}
      {!list ? <Spinner /> : list.length === 0 ? <p className="text-muted">{t("dossiers.empty")}</p> : (
        <div className="grid md:grid-cols-2 gap-3">
          {list.map((d) => (
            <Link key={d.id} href={`/dossiers/${d.id}`} className="card p-4 hover:border-border-strong transition flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <StatusChip status={d.status} />
                <span className="text-xs text-faint">{new Date(d.created_at).toLocaleString(locale)}</span>
              </div>
              <div className="display text-lg leading-snug">{d.title ?? d.brief.slice(0, 90)}</div>
              <p className="text-sm text-muted line-clamp-2">{d.brief}</p>
              <div className="flex gap-3 text-xs text-faint mt-auto"><span><FileText size={12} className="inline mr-1" />{d.n_citations} sources</span><span>{t("dossiers.cost")} {fmtUsd(d.cost_usd)}</span></div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
