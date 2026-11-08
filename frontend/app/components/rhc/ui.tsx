"use client";

import { createContext, useContext, type ReactNode } from "react";
import { AlertTriangle, Loader2, ShieldOff } from "lucide-react";
import type { Reason } from "./api";

/* Reason catalog shared by every chip (descriptions come from GET /api/rhc/reasons). */
export const ReasonsContext = createContext<Record<string, Reason>>({});

export function Card({ title, right, children, className = "" }: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg p-4 min-w-0 ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between gap-3 mb-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-text-secondary)]">{title}</h3>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, tone }: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "good" | "bad" | "warn" | "muted";
}) {
  const color =
    tone === "good" ? "text-[var(--color-success)]"
      : tone === "bad" ? "text-[var(--color-danger)]"
        : tone === "warn" ? "text-[var(--color-brand)]"
          : "text-[var(--color-text-primary)]";
  return (
    <div className="min-w-0">
      <div className="text-[11px] uppercase tracking-wider text-[var(--color-text-secondary)]">{label}</div>
      <div className={`text-lg font-semibold font-mono truncate ${color}`}>{value}</div>
      {sub && <div className="text-xs text-[var(--color-text-secondary)] truncate">{sub}</div>}
    </div>
  );
}

const TONES = {
  green: "bg-[var(--color-success)]/15 text-[var(--color-success)] border-[var(--color-success)]/30",
  red: "bg-[var(--color-danger)]/15 text-[var(--color-danger)] border-[var(--color-danger)]/30",
  amber: "bg-[var(--color-brand)]/15 text-[var(--color-brand)] border-[var(--color-brand)]/30",
  gray: "bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)] border-[var(--color-border)]",
} as const;

export type Tone = keyof typeof TONES;

export function Badge({ tone = "gray", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title}
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-semibold whitespace-nowrap ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function CodeChip({ code }: { code: string }) {
  const reasons = useContext(ReasonsContext);
  const r = reasons[code];
  const tone: Tone = r?.severity === "reject" ? "red" : r?.severity === "warn" ? "amber" : "gray";
  return (
    <Badge tone={tone} title={r ? `${r.description} (${r.category}, ${r.severity}${r.permanent ? ", permanent" : ""})` : code}>
      {code}
    </Badge>
  );
}

export function Chips({ list }: { list: string[] }) {
  if (!list.length) return <span className="text-[var(--color-text-secondary)]">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {list.map((c) => <CodeChip key={c} code={c} />)}
    </div>
  );
}

export function StateBadge({ state }: { state: string }) {
  const tone: Tone = state === "watch" ? "green" : state === "rejected" ? "red" : state === "candidate" ? "amber" : "gray";
  return <Badge tone={tone}>{state}</Badge>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)] py-6 justify-center">
      <Loader2 className="w-4 h-4 animate-spin" /> {label}
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="flex items-start gap-2 text-sm text-[var(--color-danger)] bg-[var(--color-danger)]/10 border border-[var(--color-danger)]/30 rounded p-3">
      <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
      <span className="break-words">{error}</span>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-sm text-[var(--color-text-secondary)] text-center py-6">{children}</div>;
}

export function PaperBanner() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-[var(--color-brand)]/40 bg-[var(--color-brand)]/10 px-4 py-2 text-sm">
      <span className="font-bold tracking-wider text-[var(--color-brand)]">PAPER MODE</span>
      <span className="inline-flex items-center gap-1 text-[var(--color-text-primary)]">
        <ShieldOff className="w-4 h-4" /> Live trading is disabled in code
      </span>
      <span className="text-[var(--color-text-secondary)]">
        Fills are simulated on live chain state. No real funds, no transactions, no conclusions below the sample gate.
      </span>
    </div>
  );
}

export function Table({ head, children, empty }: { head: ReactNode[]; children: ReactNode; empty?: boolean }) {
  return (
    <div className="overflow-x-auto custom-scrollbar -mx-4 px-4">
      <table className="w-full text-sm text-left">
        <thead className="text-[10px] text-[var(--color-text-secondary)] uppercase bg-[var(--color-bg-hover)]">
          <tr>{head.map((h, i) => <th key={i} className="py-2 px-3 font-semibold whitespace-nowrap">{h}</th>)}</tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
      {empty && <Empty>Nothing to show yet.</Empty>}
    </div>
  );
}

export const tr = "border-b border-[var(--color-border)] hover:bg-[var(--color-bg-hover)] transition-colors";
export const td = "py-2 px-3 align-top";
export const mono = "font-mono text-xs whitespace-nowrap";

export function pnlTone(v: number | null | undefined): "good" | "bad" | undefined {
  if (v === null || v === undefined) return undefined;
  return v > 0 ? "good" : v < 0 ? "bad" : undefined;
}

export function pnlClass(v: number | null | undefined): string {
  const t = pnlTone(v);
  return t === "good" ? "text-[var(--color-success)]" : t === "bad" ? "text-[var(--color-danger)]" : "";
}
