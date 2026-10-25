"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import clsx from "clsx";
import { api, type DocSummary, type Stats } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ErrorBox, PageHeader, Spinner } from "@/components/ui";

export default function LibraryPage() {
  const { t } = useI18n();
  const [docs, setDocs] = useState<DocSummary[] | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [type, setType] = useState<string>("");
  const [source, setSource] = useState<string>("");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.stats().then(setStats).catch(() => {}); }, []);
  useEffect(() => {
    const id = setTimeout(() => api.documents({ doc_type: type || undefined, source_kind: source || undefined, q: q || undefined, limit: 200 }).then(setDocs).catch((e) => setError(e.message)), 200);
    return () => clearTimeout(id);
  }, [type, source, q]);

  const types = stats ? Object.keys(stats.corpus.doc_types) : [];
  const sources = stats ? Array.from(new Set(stats.corpus.sources.map((s) => s.kind))) : [];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("library.title")} subtitle={t("library.subtitle")} right={stats && <div className="text-xs text-faint text-right">{stats.corpus.chunks} chunks · {stats.corpus.reviews} reviews<br />{stats.corpus.year_min ?? "?"} → {stats.corpus.year_max ?? "?"}</div>} />
      <div className="card p-3 flex flex-wrap items-center gap-3">
        <input className="input-sm flex-1 min-w-48" placeholder={t("library.search")} value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="flex gap-1 flex-wrap">
          <button onClick={() => setType("")} className={clsx("chip", !type && "chip-accent")}>{t("library.all")}</button>
          {types.map((ty) => <button key={ty} onClick={() => setType(ty)} className={clsx("chip", type === ty && "chip-accent")}>{ty} <span className="text-faint">{stats?.corpus.doc_types[ty]}</span></button>)}
        </div>
        <div className="flex gap-1 flex-wrap">
          {sources.map((s) => <button key={s} onClick={() => setSource(source === s ? "" : s)} className={clsx("chip", source === s && "chip-info")}>{s === "sample" ? t("common.sample_badge") : s}</button>)}
        </div>
      </div>
      <p className="text-xs text-faint mono">{t("library.drop_hint")}</p>
      {error && <ErrorBox message={error} />}
      {!docs ? <Spinner /> : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase tracking-wide text-faint"><th className="px-4 py-2.5">Titre</th><th className="px-4 py-2.5 hidden md:table-cell">Auteur</th><th className="px-4 py-2.5">Date</th><th className="px-4 py-2.5 hidden sm:table-cell">Type</th><th className="px-4 py-2.5 hidden lg:table-cell">Source</th><th className="px-4 py-2.5 text-right">{t("library.chunks")}</th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className="border-t border-border hover:bg-elev-2/50">
                  <td className="px-4 py-2.5"><Link href={`/library/${d.id}`} className="hover:text-accent">{d.title}</Link>{d.issue && <div className="text-xs text-faint">{d.issue}</div>}</td>
                  <td className="px-4 py-2.5 text-muted hidden md:table-cell">{d.author ?? "–"}</td>
                  <td className="px-4 py-2.5 text-muted mono text-xs">{d.published_on ?? d.year ?? "–"}</td>
                  <td className="px-4 py-2.5 hidden sm:table-cell"><span className="chip">{d.doc_type}</span></td>
                  <td className="px-4 py-2.5 hidden lg:table-cell"><span className={clsx("chip", d.source_kind === "sample" && "chip-info")}>{d.source_kind}</span></td>
                  <td className="px-4 py-2.5 text-right mono text-xs text-muted">{d.chunks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
