"use client";

import { X, ExternalLink } from "lucide-react";
import { clock, codes, EXPLORER, fmtNum, shortAddr, usePoll, type CheckEvidence, type DecisionRow, type Num, type ScreenRow } from "./api";
import RhcCandleChart from "./RhcCandleChart";
import { Badge, Card, Chips, ErrorNote, Loading, Table, mono, td, tr } from "./ui";

const CHECK_ORDER = ["market", "activity", "liquidity", "simulation", "contract", "holders", "flow", "lp"];
const CHECK_TITLE: Record<string, string> = {
  market: "Market", activity: "Activity (1h)", liquidity: "Liquidity", simulation: "Buy/sell simulation",
  contract: "Contract permissions", holders: "Holders", flow: "Flow quality (last hour)", lp: "Liquidity control",
};

function CheckCard({ name, ev }: { name: string; ev: CheckEvidence }) {
  const list = Array.isArray(ev.codes) ? ev.codes : [];
  const entries = Object.entries(ev).filter(([k]) => k !== "codes");
  return (
    <div className="rounded border border-[var(--color-border)] p-3 min-w-0">
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="font-semibold text-sm">{CHECK_TITLE[name] ?? name}</span>
        {list.length ? <Chips list={list} /> : <Badge tone="green">clear</Badge>}
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        {entries.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-[var(--color-text-secondary)] truncate">{k}</dt>
            <dd className={`${mono} truncate`} title={typeof v === "string" ? v : JSON.stringify(v)}>
              {typeof v === "string" && v.startsWith("0x") ? shortAddr(v) : fmtNum(v as Num)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function TokenReport({ poolId, onClose }: { poolId: string; onClose: () => void }) {
  const screens = usePoll<ScreenRow[]>(`/screens?pool_id=${poolId}&limit=20`, 30000);
  const decisions = usePoll<DecisionRow[]>(`/decisions?pool_id=${poolId}&limit=30`, 30000);
  const feats = usePoll<{ features: Record<string, Num> }>(`/features?pool_id=${poolId}`, 30000);
  const latest = screens.data?.[0];
  const ev = (latest?.evidence ?? {}) as Record<string, CheckEvidence | boolean>;

  return (
    <div className="fixed inset-0 z-[200] flex justify-end bg-black/50" onClick={onClose}>
      <div className="h-full w-full max-w-5xl overflow-y-auto custom-scrollbar bg-[var(--color-bg-base)] p-4 space-y-4"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-xl font-bold truncate">{latest?.symbol || "Token"} intelligence report</h2>
            <div className={`${mono} text-[var(--color-text-secondary)] break-all`}>
              pool {poolId}
              {latest?.token && (
                <a className="inline-flex items-center gap-1 ml-2 text-[var(--color-brand)]" target="_blank" rel="noreferrer"
                  href={`${EXPLORER}/token/${latest.token}`}>token <ExternalLink className="w-3 h-3" /></a>
              )}
            </div>
          </div>
          <button onClick={onClose} aria-label="Close" className="p-2 rounded hover:bg-[var(--color-bg-hover)]"><X className="w-5 h-5" /></button>
        </div>

        <Card title="Price & volume"><RhcCandleChart poolId={poolId} height={280} /></Card>

        <Card title={latest ? `Latest screening · ${clock(latest.ts)} · ${latest.duration_ms ?? 0} ms` : "Latest screening"}
          right={latest && <Badge tone={latest.verdict === "pass" ? "green" : "red"}>{latest.verdict}</Badge>}>
          <ErrorNote error={screens.error} />
          {screens.loading && !screens.data ? <Loading /> : !latest ? (
            <p className="text-sm text-[var(--color-text-secondary)]">Not screened yet.</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-4 mb-3 text-sm">
                <div><span className="text-[var(--color-text-secondary)] mr-2">Reject</span><Chips list={codes(latest.reject_codes)} /></div>
                <div><span className="text-[var(--color-text-secondary)] mr-2">Warn / info</span><Chips list={codes(latest.warn_codes)} /></div>
              </div>
              {ev._skipped_after_reject === true && (
                <p className="text-xs text-[var(--color-text-secondary)] mb-2">Later checks were skipped after the first rejection (saves RPC budget).</p>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {CHECK_ORDER.filter((k) => typeof ev[k] === "object").map((k) => <CheckCard key={k} name={k} ev={ev[k] as CheckEvidence} />)}
              </div>
            </>
          )}
        </Card>

        <Card title="Current features (point-in-time, closed candles only)">
          <ErrorNote error={feats.error} />
          {feats.data ? (
            <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-4 gap-y-1 text-xs">
              {Object.entries(feats.data.features).filter(([k]) => !["as_of", "last_bucket"].includes(k)).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-2 border-b border-[var(--color-border)] py-1">
                  <dt className="text-[var(--color-text-secondary)] truncate">{k}</dt><dd className={mono}>{fmtNum(v)}</dd>
                </div>
              ))}
            </dl>
          ) : <Loading />}
        </Card>

        <Card title="Signals & decisions for this pool">
          <Table empty={(decisions.data ?? []).length === 0} head={["Time", "Strategy", "Action", "Reasons", "Size"]}>
            {(decisions.data ?? []).map((d) => (
              <tr key={d.id} className={tr}>
                <td className={`${td} ${mono}`}>{clock(d.as_of)}</td>
                <td className={td}>{d.strategy}</td>
                <td className={td}><Badge tone={d.action === "ENTER_INTENT" ? "green" : d.action === "SETUP_DETECTED" ? "amber" : "gray"}>{d.action}</Badge></td>
                <td className={td}><Chips list={codes(d.reasons)} /></td>
                <td className={`${td} ${mono}`}>{d.size_usd ? `$${d.size_usd}` : "—"}</td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card title="Screening history">
          <Table empty={(screens.data ?? []).length === 0} head={["Time", "Verdict", "Reject", "Warn / info"]}>
            {(screens.data ?? []).map((s) => (
              <tr key={s.id} className={tr}>
                <td className={`${td} ${mono}`}>{clock(s.ts)}</td>
                <td className={td}><Badge tone={s.verdict === "pass" ? "green" : "red"}>{s.verdict}</Badge></td>
                <td className={td}><Chips list={codes(s.reject_codes)} /></td>
                <td className={td}><Chips list={codes(s.warn_codes)} /></td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </div>
  );
}
