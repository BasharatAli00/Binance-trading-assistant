"use client";

import { useState } from "react";
import { CheckCircle2, Play, XCircle } from "lucide-react";
import { clock, fmtCI, fmtNum, fmtPct, fmtUsd, rhcGet, usePoll, type BacktestSummary, type Gate, type Metrics, type Performance } from "./api";
import { Badge, Card, ErrorNote, Loading, Stat, Table, mono, pnlTone, td, tr } from "./ui";

export function Verdict({ m }: { m: Metrics }) {
  const insufficient = !m.gate.sufficient;
  return (
    <div className={`rounded border p-3 text-sm ${insufficient ? "border-[var(--color-brand)]/40 bg-[var(--color-brand)]/10" : "border-[var(--color-border)]"}`}>
      <div className="font-semibold">{m.verdict}</div>
      {insufficient && <div className="text-xs text-[var(--color-text-secondary)] mt-1">Missing: {m.gate.missing.join(" · ")}</div>}
    </div>
  );
}

export function MetricsGrid({ m }: { m: Metrics }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
      <Stat label="Trades" value={m.trades} sub={`${m.tokens} tokens · ${fmtNum(m.days, 1)} days`} />
      <Stat label="Net P&L" value={fmtUsd(m.net_pnl_usd)} tone={pnlTone(m.net_pnl_usd)} />
      <Stat label="Win rate" value={m.win_rate === null ? "—" : fmtPct(m.win_rate, 1).replace("+", "")}
        sub={`95% CI ${m.win_rate_ci95 && m.win_rate_ci95[0] !== null ? `${(Number(m.win_rate_ci95[0]) * 100).toFixed(0)}–${(Number(m.win_rate_ci95[1]) * 100).toFixed(0)}%` : "—"}`} />
      <Stat label="Expectancy / trade" value={fmtUsd(m.expectancy_usd)} tone={pnlTone(m.expectancy_usd)} sub={`CI ${fmtCI(m.expectancy_usd_ci95, true)}`} />
      <Stat label="Profit factor" value={fmtNum(m.profit_factor, 2)} sub={`CI ${fmtCI(m.profit_factor_ci95)}`} />
      <Stat label="Max drawdown" value={m.max_drawdown_pct === null || m.trades === 0 ? "—" : `${m.max_drawdown_pct}%`} />
      <Stat label="Avg win / loss" value={`${fmtUsd(m.avg_win_usd)} / ${fmtUsd(m.avg_loss_usd)}`} sub={`payoff ${fmtNum(m.payoff_ratio, 2)}`} />
      <Stat label="Expectancy (R)" value={fmtNum(m.expectancy_r, 2)} sub={`CI ${fmtCI(m.expectancy_r_ci95)}`} />
      <Stat label="Trades / day" value={fmtNum(m.trades_per_day, 1)} />
      <Stat label="Avg hold" value={m.avg_hold_min === null ? "—" : `${fmtNum(m.avg_hold_min, 0)} min`} />
      <Stat label="Exit reasons" value={<span className="text-xs">{Object.entries(m.exit_reasons).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"}</span>} />
    </div>
  );
}

function Breakdown({ title, groups }: { title: string; groups: Record<string, Metrics> }) {
  const rows = Object.entries(groups);
  return (
    <Card title={title}>
      <Table empty={rows.length === 0} head={["Group", "Trades", "Net P&L", "Win rate", "Expectancy", "Exp. CI", "PF", "Max DD", "Verdict"]}>
        {rows.map(([g, m]) => (
          <tr key={g} className={tr}>
            <td className={`${td} font-semibold`}>{g}</td>
            <td className={`${td} ${mono}`}>{m.trades}</td>
            <td className={`${td} ${mono}`}>{fmtUsd(m.net_pnl_usd)}</td>
            <td className={`${td} ${mono}`}>{m.win_rate === null ? "—" : `${(m.win_rate * 100).toFixed(0)}%`}</td>
            <td className={`${td} ${mono}`}>{fmtUsd(m.expectancy_usd)}</td>
            <td className={`${td} ${mono}`}>{fmtCI(m.expectancy_usd_ci95, true)}</td>
            <td className={`${td} ${mono}`}>{fmtNum(m.profit_factor, 2)}</td>
            <td className={`${td} ${mono}`}>{m.max_drawdown_pct}%</td>
            <td className={`${td} text-xs`}>{m.verdict}</td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

function Backtest() {
  const [days, setDays] = useState(1);
  const [res, setRes] = useState<BacktestSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setRes(await rhcGet<BacktestSummary>(`/backtest?days=${days}`));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Backtest & walk-forward (recorded candles)"
      right={
        <div className="flex items-center gap-2 text-xs">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
            className="bg-[var(--color-bg-base)] border border-[var(--color-border)] rounded px-2 py-1">
            {[0.5, 1, 2, 3].map((d) => <option key={d} value={d}>{d} day{d === 1 ? "" : "s"}</option>)}
          </select>
          <button onClick={run} disabled={busy}
            className="inline-flex items-center gap-1 px-3 py-1 rounded bg-[var(--color-brand)] text-black font-semibold disabled:opacity-50">
            <Play className="w-3 h-3" /> {busy ? "Running…" : "Run"}
          </button>
        </div>
      }>
      <ErrorNote error={err} />
      {!res && !busy && <p className="text-sm text-[var(--color-text-secondary)]">Replays the same signals, risk and exit rules over stored candles. Fills are modelled from candles because historical pool state is not available, so treat it as a sanity check, not proof.</p>}
      {busy && <Loading label="Backtesting…" />}
      {res && (
        <div className="space-y-3">
          <div className="text-xs text-[var(--color-text-secondary)]">
            Run #{res.run_id} · {res.pools} pools · {clock(res.window[0])} → {clock(res.window[1])} · config {res.config_hash} ·
            decisions {Object.entries(res.decisions).map(([k, v]) => `${k} ${v}`).join(", ") || "none"}
          </div>
          <Verdict m={res.overall} />
          <MetricsGrid m={res.overall} />
          <div>
            <div className="text-[11px] uppercase text-[var(--color-text-secondary)] mb-1">Walk-forward folds (fixed parameters)</div>
            <div className="flex flex-wrap gap-2">
              {res.walk_forward.folds.map((f) => (
                <Badge key={f.fold} tone={f.net_pnl_usd > 0 ? "green" : f.net_pnl_usd < 0 ? "red" : "gray"}>
                  fold {f.fold}: {f.trades} trades, {fmtUsd(f.net_pnl_usd)}
                </Badge>
              ))}
            </div>
            <div className="text-xs mt-2">Hold-out (last 20%): {res.walk_forward.holdout.trades} trades · {res.walk_forward.holdout.verdict}</div>
          </div>
          <Breakdown title="Backtest by strategy" groups={res.by_strategy} />
        </div>
      )}
    </Card>
  );
}

function GoLive() {
  // The gate runs a backtest server-side, so load once and refresh on demand (no tight polling).
  const { data, error, refresh } = usePoll<Gate>("/go-live-gate", 3_600_000);
  return (
    <Card title="Go-live gate (checklist before real execution may even be considered)"
      right={
        <div className="flex items-center gap-2">
          <button onClick={refresh} className="text-xs px-2 py-1 rounded border border-[var(--color-border)] text-[var(--color-text-secondary)]">
            Re-evaluate
          </button>
          {data && <Badge tone={data.ready ? "green" : "red"}>{data.ready ? "ready" : "not ready"}</Badge>}
        </div>
      }>
      <ErrorNote error={error} />
      {!data ? <Loading /> : (
        <ul className="space-y-1 text-sm">
          {data.checks.map((c) => (
            <li key={c.check} className="flex items-start gap-2">
              {c.pass ? <CheckCircle2 className="w-4 h-4 mt-0.5 text-[var(--color-success)] shrink-0" />
                : <XCircle className="w-4 h-4 mt-0.5 text-[var(--color-danger)] shrink-0" />}
              <span>{c.check}<span className="text-xs text-[var(--color-text-secondary)] ml-2">{typeof c.detail === "string" ? c.detail : JSON.stringify(c.detail)}</span></span>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-[var(--color-text-secondary)] mt-3">Passing this enables nothing. Live trading stays disabled in code until a separate, approved change.</p>
    </Card>
  );
}

export default function PerformancePanel() {
  const { data, error, loading } = usePoll<Performance>("/performance", 30000);
  return (
    <div className="space-y-4">
      <Card title="Forward paper trading performance">
        <ErrorNote error={error} />
        {loading && !data ? <Loading /> : data && (
          <div className="space-y-3"><Verdict m={data.overall} /><MetricsGrid m={data.overall} /></div>
        )}
      </Card>
      {data && <Breakdown title="By strategy" groups={data.by_strategy} />}
      {data && <Breakdown title="By market regime" groups={data.by_regime} />}
      <Backtest />
      <GoLive />
    </div>
  );
}
