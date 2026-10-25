"use client";

import Link from "next/link";
import { ExternalLink, FileText } from "lucide-react";
import clsx from "clsx";
import { api, type Hit } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function SourceCard({ hit, label, highlighted, compact }: { hit: Hit; label?: string; highlighted?: boolean; compact?: boolean }) {
  const { t } = useI18n();
  const when = hit.published_on ?? (hit.year ? String(hit.year) : null);
  const isPdf = !!hit.file_path?.toLowerCase().endsWith(".pdf");
  return (
    <div id={label ? `src-${label}` : undefined} className={clsx("card p-3 text-sm transition", highlighted && "ring-2 ring-accent")}>
      <div className="flex items-start gap-2">
        {label && <span className="cite shrink-0 mt-0.5">{label.startsWith("S-") ? label.slice(2, 6) : label}</span>}
        <div className="min-w-0 flex-1">
          <div className="font-medium leading-snug truncate">{hit.title}</div>
          <div className="text-xs text-faint mt-0.5 flex flex-wrap gap-x-2">
            {hit.author && <span>{hit.author}</span>}
            {when && <span>{when}</span>}
            {hit.issue && <span className="truncate">{hit.issue}</span>}
            {hit.page && <span>{t("explore.page")} {hit.page}</span>}
          </div>
          {!compact && <p className="text-muted mt-2 line-clamp-4 leading-relaxed">{hit.text}</p>}
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <span className="chip">{hit.doc_type}</span>
            <span className={clsx("chip", hit.source_kind === "sample" && "chip-info")}>{hit.source_kind === "sample" ? t("common.sample_badge") : hit.source_kind}</span>
            <Link href={`/library/${hit.document_id}`} className="chip hover:text-accent"><FileText size={12} /> {t("explore.open")}</Link>
            {isPdf && <a href={api.pdfUrl(hit.document_id, hit.page)} target="_blank" rel="noreferrer" className="chip hover:text-accent"><ExternalLink size={12} /> PDF</a>}
            {hit.url && <a href={hit.url} target="_blank" rel="noreferrer" className="chip hover:text-accent"><ExternalLink size={12} /> URL</a>}
          </div>
        </div>
      </div>
    </div>
  );
}
