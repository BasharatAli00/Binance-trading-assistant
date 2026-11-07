"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { clock, codes, fmtNum, fmtPrice, shortAddr, usePoll, type DecisionRow } from "./api";
import { Badge, Card, Chips, ErrorNote, Loading, Table, mono, td, tr, type Tone } from "./ui";

const ACTIONS = ["ENTER_INTENT", "SETUP_DETECTED", "NOT_CONFIRMED", "EXPIRED", "REJECTED_RISK"] as const;
const ACTION_TONE: Record<string, Tone> = {
  ENTER_INTENT: "green", SETUP_DETECTED: "amber", REJECTED_RISK: "red", NOT_CONFIRMED: "gray", EXPIRED: "gray",
};

function Evidence({ d }: { d: DecisionRow }) {
  const ev = d.evidence || {};
  const conds = Object.entries(ev.conditions || {});
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 py-2">
      <div>
        <div className="text-[11px] uppercase text-[var(--color-text-secondary)] mb-1">Strategy conditions</div>
        <table className="w-full text-xs">
          <tbody>
            {conds.map(([k, c]) => (
              <tr key={k} className="border-b border-[var(--color-border)]">
                <td className="py-1 pr-2">{c.ok ? "✓" : "✗"} {k}</td>
                <td className={`py-1 pr-2 ${mono}`}>{fmtNum(c.value)}</td>
                <td className={`py-1 ${mono} text-[var(--color-text-secondary)]`}>{c.op} {fmtNum(c.threshold)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <div className="text-[11px] uppercase text-[var(--color-text-secondary)] mb-1">Features at decision</div>
        <dl className="grid grid-cols-2 gap-x-2 text-xs">
          {Object.entries(ev.features || {}).map(([k, v]) => (
            <div key={k} className="contents"><dt className="text-[var(--color-text-secondary)] truncate">{k}</dt><dd className={mono}>{fmtNum(v)}</dd></div>
          ))}
        </dl>
      </div>
      <div className="text-xs space-y-2">
        {ev.regime && (
          <div><div className="text-[11px] uppercase text-[var(--color-text-secondary)] mb-1">Regime</div>
            {ev.regime.label ?? "—"} · pct {fmtNum(ev.regime.pct)} · ETH 1h {fmtNum(ev.regime.eth_ret_1h)}
            {ev.regime.no_trade && ev.regime.no_trade.length > 0 && <div className="mt-1"><Chips list={ev.regime.no_trade} /></div>}
          </div>
        )}
        {ev.risk && (
          <div><div className="text-[11px] uppercase text-[var(--color-text-secondary)] mb-1">Risk & sizing</div>
            <pre className={`${mono} whitespace-pre-wrap break-words`}>{JSON.stringify(ev.risk, null, 1)}</pre>
          </div>
        )}
        {ev.broker_result && (
          <div><div className="text-[11px] uppercase text-[var(--color-text-secondary)] mb-1">Broker</div>
            <pre className={`${mono} whitespace-pre-wrap break-words`}>{JSON.stringify(ev.broker_result, null, 1)}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

export default function DecisionsPanel({ compact = false }: { compact?: boolean }) {
  const [action, setAction] = useState<string>("all");
  const [open, setOpen] = useState<number | null>(null);
  const q = action === "all" ? "" : `&action=${action}`;
  const { data, error, loading } = usePoll<DecisionRow[]>(`/decisions?limit=${compact ? 8 : 200}${q}`, 20000);
  const rows = data ?? [];

  return (
    <Card title={compact ? "Recent signals & decisions" : "Active signals, decisions & rejections"}
      right={!compact && (
        <div className="flex flex-wrap gap-1">
          {(["all", ...ACTIONS] as const).map((a) => (
            <button key={a} onClick={() => setAction(a)}
              className={`text-xs px-2 py-1 rounded border ${action === a ? "border-[var(--color-brand)] text-[var(--color-brand)]" : "border-[var(--color-border)] text-[var(--color-text-secondary)]"}`}>
              {a.toLowerCase().replace("_", " ")}
            </button>
          ))}
        </div>
      )}>
      <ErrorNote error={error} />
      {loading && !data ? <Loading /> : (
        <Table empty={rows.length === 0}
          head={compact ? ["", "Time", "Token", "Strategy", "Action", "Entry", "Size", "Reasons"]
            : ["", "Time", "Token", "Strategy", "Action", "Entry", "Stop", "Targets", "Size", "Reasons"]}>
          {rows.map((d) => (
            <Fragment key={d.id}>
              <tr className={`${tr} cursor-pointer`} onClick={() => setOpen(open === d.id ? null : d.id)}>
                <td className={td}>{open === d.id ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}</td>
                <td className={`${td} ${mono}`}>{clock(d.as_of)}</td>
                <td className={`${td} font-semibold whitespace-nowrap`}>{d.symbol || shortAddr(d.token)}</td>
                <td className={`${td} whitespace-nowrap`}>{d.strategy}</td>
                <td className={td}><Badge tone={ACTION_TONE[d.action] ?? "gray"}>{d.action}</Badge></td>
                <td className={`${td} ${mono}`}>{fmtPrice(d.entry_ref)}</td>
                {!compact && <td className={`${td} ${mono}`}>{fmtPrice(d.stop)}</td>}
                {!compact && <td className={`${td} ${mono}`}>{codes(d.targets).map((t) => fmtPrice(Number(t))).join(" / ") || "—"}</td>}
                <td className={`${td} ${mono}`}>{d.size_usd ? `$${d.size_usd}` : "—"}</td>
                <td className={td}><Chips list={codes(d.reasons)} /></td>
              </tr>
              {open === d.id && (
                <tr className="border-b border-[var(--color-border)]"><td colSpan={10} className="px-3"><Evidence d={d} /></td></tr>
              )}
            </Fragment>
          ))}
        </Table>
      )}
    </Card>
  );
}
