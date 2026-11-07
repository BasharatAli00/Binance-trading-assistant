"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { ago, clock, codes, fmtPct, fmtPrice, fmtUsd, shortAddr, usePoll, type PaperFill, type PaperPosition } from "./api";
import { Badge, Card, ErrorNote, Loading, Table, mono, pnlClass, td, tr } from "./ui";

function Fills({ id }: { id: number }) {
  const { data } = usePoll<PaperFill[]>(`/paper/fills?position_id=${id}`, 60000);
  if (!data) return <Loading />;
  return (
    <table className="w-full text-xs my-2">
      <tbody>
        {data.map((f) => {
          let detail = "";
          try {
            const d = f.detail ? (JSON.parse(f.detail) as Record<string, unknown>) : {};
            detail = Object.entries(d).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => `${k}=${String(v)}`).join(" · ");
          } catch { detail = f.detail || ""; }
          return (
            <tr key={f.id} className="border-b border-[var(--color-border)]">
              <td className={`py-1 pr-2 ${mono}`}>{clock(f.ts)}</td>
              <td className="py-1 pr-2">{f.side}</td>
              <td className="py-1 pr-2">{f.reason}</td>
              <td className={`py-1 pr-2 ${mono}`}>{fmtUsd(f.usd)}</td>
              <td className={`py-1 pr-2 ${mono}`}>gas {fmtUsd(f.gas_usd, 3)}</td>
              <td className={`py-1 pr-2 ${mono}`}>{fmtPrice(f.price_usd)}</td>
              <td className="py-1 pr-2">{f.ok ? "ok" : <span className="text-[var(--color-danger)]">failed</span>}</td>
              <td className="py-1 text-[var(--color-text-secondary)] break-all">{detail}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function PositionsTable({ status, title, compact }: { status: "open" | "closed" | "stuck" | null; title: string; compact?: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  const { data, error, loading } = usePoll<PaperPosition[]>(`/paper/positions?limit=${compact ? 6 : 200}${status ? `&status=${status}` : ""}`, 15000);
  const rows = data ?? [];
  const closedView = status !== "open";
  return (
    <Card title={title}>
      <ErrorNote error={error} />
      {loading && !data ? <Loading /> : (
        <Table empty={rows.length === 0}
          head={["", "Token", "Strategy", "Status", "Opened", "Entry", "Stop", "Targets", "Cost",
            ...(closedView ? ["Proceeds", "P&L", "Exit"] : ["TP1", "Time stop"])]}>
          {rows.map((p) => {
            const pct = p.realized_usd !== null && p.cost_usd ? p.realized_usd / p.cost_usd : null;
            return (
              <Fragment key={p.id}>
                <tr className={`${tr} cursor-pointer`} onClick={() => setOpen(open === p.id ? null : p.id)}>
                  <td className={td}>{open === p.id ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}</td>
                  <td className={`${td} ${mono}`}>{shortAddr(p.token)}</td>
                  <td className={td}>{p.strategy}</td>
                  <td className={td}><Badge tone={p.status === "open" ? "amber" : p.status === "stuck" ? "red" : "gray"}>{p.status}</Badge></td>
                  <td className={`${td} ${mono}`}>{ago(p.opened_ts)}</td>
                  <td className={`${td} ${mono}`}>{fmtPrice(p.entry_price)}</td>
                  <td className={`${td} ${mono}`}>{fmtPrice(p.stop)}</td>
                  <td className={`${td} ${mono}`}>{codes(p.targets).map((t) => fmtPrice(Number(t))).join(" / ")}</td>
                  <td className={`${td} ${mono}`}>{fmtUsd(p.cost_usd)}</td>
                  {closedView ? (
                    <>
                      <td className={`${td} ${mono}`}>{fmtUsd(p.proceeds_usd)}</td>
                      <td className={`${td} ${mono} ${pnlClass(p.realized_usd)}`}>{fmtUsd(p.realized_usd)} ({fmtPct(pct)})</td>
                      <td className={td}>{p.exit_reason ?? "—"}</td>
                    </>
                  ) : (
                    <>
                      <td className={td}>{p.tp1_done ? "taken" : "—"}</td>
                      <td className={`${td} ${mono}`}>{clock(p.time_stop_ts)}</td>
                    </>
                  )}
                </tr>
                {open === p.id && (
                  <tr className="border-b border-[var(--color-border)]"><td colSpan={12} className="px-3"><Fills id={p.id} /></td></tr>
                )}
              </Fragment>
            );
          })}
        </Table>
      )}
    </Card>
  );
}

export default function PaperPanel({ compact = false }: { compact?: boolean }) {
  if (compact) return <PositionsTable status="open" title="Open paper positions" compact />;
  return (
    <div className="space-y-4">
      <PositionsTable status="open" title="Open paper positions" />
      <PositionsTable status={null} title="Paper trade history (closed, stuck and open)" />
      <p className="text-xs text-[var(--color-text-secondary)]">
        Entries and exits are simulated through each pool&apos;s own contract on live chain state, after a latency delay,
        with gas, a safety haircut and a failed-transaction rate. A position that cannot be sold is booked as a 100% loss (stuck).
      </p>
    </div>
  );
}
