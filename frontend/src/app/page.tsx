"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Send, Square, ThumbsDown, ThumbsUp, SlidersHorizontal, Zap } from "lucide-react";
import clsx from "clsx";
import { api, askStream, type AskEvent, type Filters, type Hit } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Markdown } from "@/components/Markdown";
import { SourceCard } from "@/components/SourceCard";
import { PageHeader, Spinner, fmtMs, fmtUsd } from "@/components/ui";

type Turn = {
  id: string;
  question: string;
  answer: string;
  sources: Hit[];
  route?: string;
  via_llm?: boolean;
  keywords?: string[];
  filters?: Filters;
  cached?: { similarity: number; cached_question: string };
  notices: string[];
  redirectBi?: boolean;
  done?: Extract<AskEvent, { type: "done" }>;
  error?: string;
  feedback?: 1 | -1;
  streaming: boolean;
};

const DOC_TYPES = ["review", "article", "poll", "interview", "wiki", "issue"];

export default function AskPage() {
  const { t, tl, locale } = useI18n();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [filters, setFilters] = useState<Filters>({ doc_types: [] });
  const [noCache, setNoCache] = useState(false);
  const [activeCite, setActiveCite] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const streaming = turns.some((x) => x.streaming);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [turns]);

  const update = useCallback((id: string, fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((x) => (x.id === id ? fn(x) : x))), []);

  const ask = useCallback(async (question: string) => {
    const q = question.trim();
    if (!q || streaming) return;
    const id = crypto.randomUUID();
    setInput("");
    setTurns((ts) => [...ts, { id, question: q, answer: "", sources: [], notices: [], streaming: true }]);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await askStream({ question: q, lang: locale, filters, use_cache: !noCache }, (ev) => {
        update(id, (x) => {
          switch (ev.type) {
            case "route": return { ...x, route: ev.route, via_llm: ev.via_llm, keywords: ev.keywords, filters: ev.filters };
            case "sources": return { ...x, sources: ev.hits };
            case "cached": return { ...x, cached: { similarity: ev.similarity, cached_question: ev.cached_question } };
            case "token": return { ...x, answer: x.answer + ev.text };
            case "notice": return { ...x, notices: [...x.notices, ev.text] };
            case "redirect": return { ...x, redirectBi: true, streaming: false };
            case "done": return { ...x, done: ev, route: ev.route, streaming: false };
            case "error": return { ...x, error: ev.message, streaming: false };
          }
        });
      }, ctrl.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") update(id, (x) => ({ ...x, error: (e as Error).message }));
    } finally {
      update(id, (x) => ({ ...x, streaming: false }));
    }
  }, [filters, locale, noCache, streaming, update]);

  const stop = () => abortRef.current?.abort();

  const sendFeedback = async (turn: Turn, score: 1 | -1) => {
    if (!turn.done?.trace_id) return;
    update(turn.id, (x) => ({ ...x, feedback: score }));
    try { await api.feedback(turn.done.trace_id, score); } catch {}
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("ask.title")} subtitle={t("ask.subtitle")} />

      {turns.length === 0 && (
        <div className="grid sm:grid-cols-2 gap-3">
          {tl("ask.examples").map((ex) => (
            <button key={ex} onClick={() => ask(ex)} className="card p-4 text-left text-sm text-muted hover:text-fg hover:border-border-strong transition">
              <Zap size={14} className="inline mr-2 text-accent" />{ex}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-col gap-8">
        {turns.map((turn) => (
          <TurnView key={turn.id} turn={turn} activeCite={activeCite} setActiveCite={setActiveCite} onFeedback={sendFeedback} />
        ))}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={(e) => { e.preventDefault(); ask(input); }} className="sticky bottom-4 card p-3 flex flex-col gap-3 shadow-2xl">
        <div className="flex gap-2 items-end">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={2} placeholder={t("ask.placeholder")} className="input resize-none !py-2.5"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); } }} />
          <button type="button" onClick={() => setShowFilters((s) => !s)} className={clsx("btn btn-ghost !px-3", showFilters && "text-accent")} title={t("ask.filters")}><SlidersHorizontal size={16} /></button>
          {streaming ? (
            <button type="button" onClick={stop} className="btn btn-ghost"><Square size={14} /> {t("ask.stop")}</button>
          ) : (
            <button type="submit" disabled={!input.trim()} className="btn btn-primary"><Send size={14} /> {t("ask.send")}</button>
          )}
        </div>
        {showFilters && (
          <div className="flex flex-wrap items-center gap-3 text-sm pt-1 border-t border-border">
            <label className="flex items-center gap-1.5">{t("ask.year_from")}<input type="number" className="input-sm w-24" value={filters.year_from ?? ""} onChange={(e) => setFilters({ ...filters, year_from: e.target.value ? Number(e.target.value) : null })} /></label>
            <label className="flex items-center gap-1.5">{t("ask.year_to")}<input type="number" className="input-sm w-24" value={filters.year_to ?? ""} onChange={(e) => setFilters({ ...filters, year_to: e.target.value ? Number(e.target.value) : null })} /></label>
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-muted">{t("ask.doc_types")}</span>
              {DOC_TYPES.map((d) => {
                const on = filters.doc_types?.includes(d);
                return <button type="button" key={d} onClick={() => setFilters({ ...filters, doc_types: on ? filters.doc_types!.filter((x) => x !== d) : [...(filters.doc_types ?? []), d] })} className={clsx("chip", on && "chip-accent")}>{d}</button>;
              })}
            </div>
            <label className="flex items-center gap-1.5 ml-auto text-muted"><input type="checkbox" checked={noCache} onChange={(e) => setNoCache(e.target.checked)} /> {t("ask.no_cache")}</label>
          </div>
        )}
      </form>
    </div>
  );
}

function TurnView({ turn, activeCite, setActiveCite, onFeedback }: { turn: Turn; activeCite: string | null; setActiveCite: (s: string | null) => void; onFeedback: (t: Turn, s: 1 | -1) => void }) {
  const { t } = useI18n();
  const shown: Hit[] = turn.done?.citations?.length ? turn.done.citations : turn.sources;
  const onCite = (ref: string) => { setActiveCite(ref); document.getElementById(`src-${ref}`)?.scrollIntoView({ behavior: "smooth", block: "center" }); };
  return (
    <div className="grid lg:grid-cols-[1fr_320px] gap-5">
      <div className="flex flex-col gap-3 min-w-0">
        <div className="self-end max-w-[90%] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm" style={{ background: "var(--jz-slate)", color: "var(--jz-cream)" }}>{turn.question}</div>
        <div className="card p-4 md:p-5">
          <div className="flex flex-wrap items-center gap-2 text-xs mb-3">
            {turn.route && <span className={clsx("chip", turn.route === "fallback_keyword" ? "chip-danger" : "chip-accent")}>{t("ask.route")}: {turn.route}</span>}
            {turn.via_llm === false && turn.route && turn.route !== "cache" && <span className="chip">heuristic router</span>}
            {turn.cached && <span className="chip chip-ok" title={turn.cached.cached_question}>{t("ask.cached")} · {(turn.cached.similarity * 100).toFixed(1)}%</span>}
            {turn.filters && Object.keys(turn.filters).length > 0 && <span className="chip mono">{JSON.stringify(turn.filters)}</span>}
            {turn.notices.map((n, i) => <span key={i} className="chip chip-info">{n}</span>)}
          </div>
          {turn.redirectBi && <p className="text-sm text-muted">{t("ask.redirect_bi")} <a className="text-accent underline" href={`/insights?q=${encodeURIComponent(turn.question)}`}>Insights →</a></p>}
          {turn.error && <p className="text-sm" style={{ color: "#f0b5b5" }}>{t("common.error")}: {turn.error}</p>}
          {turn.answer ? <Markdown text={turn.answer} onCite={onCite} /> : turn.streaming && <Spinner label={t("ask.thinking")} />}
          {turn.done && (
            <div className="flex flex-wrap items-center gap-3 mt-4 pt-3 border-t border-border text-xs text-faint">
              <span>{t("ask.latency")} {fmtMs(turn.done.latency_ms)}</span>
              <span>{t("ask.cost")} {fmtUsd(turn.done.cost_usd)}</span>
              {turn.done.model && <span className="mono">{turn.done.model}</span>}
              <span className="ml-auto flex items-center gap-1">
                <button onClick={() => onFeedback(turn, 1)} className={clsx("btn btn-ghost !p-1.5", turn.feedback === 1 && "text-ok")} title={t("ask.feedback_up")}><ThumbsUp size={14} /></button>
                <button onClick={() => onFeedback(turn, -1)} className={clsx("btn btn-ghost !p-1.5", turn.feedback === -1 && "text-danger")} title={t("ask.feedback_down")}><ThumbsDown size={14} /></button>
                {turn.feedback && <span>{t("ask.feedback_thanks")}</span>}
              </span>
            </div>
          )}
        </div>
      </div>
      <aside className="flex flex-col gap-2 lg:max-h-[70vh] lg:overflow-auto lg:sticky lg:top-6">
        {shown.length > 0 && <div className="text-xs uppercase tracking-wide text-faint px-1">{t("ask.sources")} · {shown.length}</div>}
        {shown.map((h) => <SourceCard key={h.chunk_id} hit={h} label={String(h.n ?? "")} highlighted={activeCite === String(h.n)} compact />)}
      </aside>
    </div>
  );
}
