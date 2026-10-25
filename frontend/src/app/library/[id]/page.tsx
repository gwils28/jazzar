"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ArrowLeft, ExternalLink, Star } from "lucide-react";
import { api, type DocDetail } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ErrorBox, Spinner } from "@/components/ui";

export default function DocumentPage() {
  return <Suspense fallback={<Spinner />}><DocumentPageInner /></Suspense>;
}

function DocumentPageInner() {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();
  const [d, setD] = useState<DocDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.document(id).then(setD).catch((e) => setError(e.message)); }, [id]);
  if (error) return <ErrorBox message={error} />;
  if (!d) return <Spinner />;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/library" className="btn btn-ghost !px-3"><ArrowLeft size={14} /> {t("library.back")}</Link>
        <span className="chip">{d.doc_type}</span>
        <span className="chip">{d.source_kind === "sample" ? t("common.sample_badge") : d.source_name}</span>
        {d.has_pdf && <a href={api.pdfUrl(d.id)} target="_blank" rel="noreferrer" className="btn btn-ghost ml-auto"><ExternalLink size={14} /> {t("library.open_pdf")}</a>}
        {d.url && <a href={d.url} target="_blank" rel="noreferrer" className="btn btn-ghost ml-auto"><ExternalLink size={14} /> URL</a>}
      </div>
      <div>
        <h1 className="display text-3xl">{d.title}</h1>
        <div className="text-muted mt-1 flex flex-wrap gap-x-3 text-sm">{d.author && <span>{d.author}</span>}{(d.published_on ?? d.year) && <span>{d.published_on ?? d.year}</span>}{d.issue && <span>{d.issue}</span>}</div>
      </div>
      {d.reviews.length > 0 && (
        <div className="grid sm:grid-cols-2 gap-3">
          {d.reviews.map((r, i) => (
            <div key={i} className="card-2 p-4 flex items-center gap-4">
              <div className="display text-3xl text-accent flex items-center gap-1">{r.rating ?? "–"}<Star size={18} fill="currentColor" /></div>
              <div className="text-sm"><div className="font-medium">{r.album_title}</div><div className="text-muted">{r.artist} · {r.label ?? "?"} · {r.release_year ?? "?"}</div>{r.genre && <span className="chip mt-1">{r.genre}</span>}</div>
            </div>
          ))}
        </div>
      )}
      <div className="grid lg:grid-cols-[1fr_280px] gap-5">
        <section className="flex flex-col gap-3">
          <div className="text-xs uppercase tracking-wide text-faint">{t("library.excerpts")} · {d.chunks.length}</div>
          {d.chunks.map((c) => (
            <div key={c.id} className="card p-4 text-sm leading-relaxed">
              <div className="text-[11px] text-faint mono mb-1.5">#{c.ordinal + 1}{c.page ? ` · p. ${c.page}` : ""}{d.has_pdf && c.page ? <a className="ml-2 text-accent" href={api.pdfUrl(d.id, c.page)} target="_blank" rel="noreferrer">PDF ↗</a> : null}</div>
              <p className="whitespace-pre-line">{c.text}</p>
            </div>
          ))}
        </section>
        <aside className="card p-4 text-xs mono text-muted h-fit">
          <div className="uppercase tracking-wide text-faint mb-2">{t("library.metadata")}</div>
          <pre className="whitespace-pre-wrap break-words">{JSON.stringify({ language: d.language, file_path: d.file_path, ...d.meta }, null, 1)}</pre>
        </aside>
      </div>
    </div>
  );
}
