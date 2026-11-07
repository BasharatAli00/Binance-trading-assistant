"use client";

import { useState } from "react";
import { Power } from "lucide-react";
import { clock, fmtUsd, rhcPost, usePoll, type Risk } from "./api";
import { Badge, Card, Chips, ErrorNote, Loading, Stat, pnlTone } from "./ui";

function Meter({ label, value, max, invert = false, fmt = fmtUsd }: {
  label: string; value: number; max: number; invert?: boolean; fmt?: (v: number) => string;
}) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (Math.abs(value) / Math.abs(max)) * 100)) : 0;
  const hot = pct >= 80;
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-[var(--color-text-secondary)]">{label}</span>
        <span className="font-mono">{fmt(value)} / {fmt(max)}</span>
      </div>
      <div className="h-2 rounded bg-[var(--color-bg-hover)] overflow-hidden">
        <div className={`h-full ${hot ? "bg-[var(--color-danger)]" : invert ? "bg-[var(--color-brand)]" : "bg-[var(--color-success)]"}`}
          style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function RiskPanel({ compact = false }: { compact?: boolean }) {
  const { data, error, loading, refresh } = usePoll<Risk>("/risk", 15000);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const toggle = async (enabled: boolean) => {
    if (enabled === false && !window.confirm("Turn the kill switch OFF and allow new paper entries again?")) return;
    setBusy(true);
    setErr(null);
    try {
      await rhcPost("/kill-switch", { enabled, reason: reason || (enabled ? "manual stop from UI" : "manual resume from UI") });
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const killed = !!data && (data.kill_switch.db.enabled || data.kill_switch.env);
  return (
    <Card title="Risk monitor"
      right={data && <Badge tone={killed ? "red" : "green"}>{killed ? "KILL SWITCH ON" : "entries allowed"}</Badge>}>
      <ErrorNote error={error || err} />
      {loading && !data ? <Loading /> : data && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <Stat label="Paper equity" value={fmtUsd(data.equity_usd)} />
            <Stat label="Today's P&L" value={fmtUsd(data.daily_pnl_usd)} tone={pnlTone(data.daily_pnl_usd)}
              sub={`realized ${fmtUsd(data.realized_today_usd)} · open ${fmtUsd(data.unrealized_usd)}`} />
            <Stat label="Open positions" value={`${data.open_positions} / ${data.max_open}`} />
            <Stat label="Regime" value={data.regime ?? "unknown"} />
          </div>
          <Meter label="Exposure" value={data.exposure_usd} max={data.max_exposure_usd} invert />
          <Meter label="Daily loss used" value={Math.min(0, data.daily_pnl_usd)} max={data.daily_loss_limit_usd} />
          <div className="text-sm">
            <span className="text-[var(--color-text-secondary)] mr-2">No-trade conditions</span>
            <Chips list={[...data.no_trade, ...(data.daily_limit_hit ? ["DAILY_LOSS_LIMIT"] : [])]} />
          </div>
          {!compact && (
            <div className="border-t border-[var(--color-border)] pt-3 space-y-2">
              <div className="text-xs text-[var(--color-text-secondary)]">
                Kill switch blocks every new paper entry (exits still run).
                {data.kill_switch.db.ts ? ` Last change ${clock(data.kill_switch.db.ts)}${data.kill_switch.db.reason ? `: ${data.kill_switch.db.reason}` : ""}.` : ""}
                {data.kill_switch.env ? " RHC_KILL_SWITCH is set in the environment." : ""}
              </div>
              <div className="flex flex-wrap gap-2 items-center">
                <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (optional)"
                  className="flex-1 min-w-[12rem] bg-[var(--color-bg-base)] border border-[var(--color-border)] rounded px-2 py-1 text-sm" />
                {data.kill_switch.db.enabled ? (
                  <button disabled={busy} onClick={() => toggle(false)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded border border-[var(--color-success)] text-[var(--color-success)] text-sm font-semibold disabled:opacity-50">
                    <Power className="w-4 h-4" /> Resume entries
                  </button>
                ) : (
                  <button disabled={busy} onClick={() => toggle(true)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-[var(--color-danger)] text-white text-sm font-semibold disabled:opacity-50">
                    <Power className="w-4 h-4" /> Activate kill switch
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
