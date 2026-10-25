"use client";

import type { ReactNode } from "react";

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
      <div>
        <h1 className="display text-3xl md:text-4xl tracking-tight">{title}</h1>
        {subtitle && <p className="text-muted mt-1.5">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted">
      <span className="inline-flex gap-1"><span className="dot" /><span className="dot" /><span className="dot" /></span>
      {label}
    </span>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="card p-3 text-sm border-danger/40 text-[#f0b5b5]" style={{ borderColor: "color-mix(in srgb, var(--danger) 50%, transparent)" }}>{message}</div>;
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs uppercase tracking-wide text-faint">{label}</div>
      <div className="display text-2xl mt-1">{value}</div>
      {hint && <div className="text-xs text-muted mt-1">{hint}</div>}
    </div>
  );
}

export function fmtMs(ms?: number | null) {
  if (ms == null) return "–";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}
export function fmtUsd(v?: number | null) {
  if (v == null) return "–";
  return v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(3)}`;
}
