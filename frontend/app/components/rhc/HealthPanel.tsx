"use client";

import { ago, fmtNum, fmtPct, usePoll, type Health } from "./api";
import { Badge, Card, ErrorNote, Loading, Stat, Table, mono, td, tr, type Tone } from "./ui";

function statusTone(s: string | undefined): Tone {
  if (!s) return "gray";
  if (s === "running") return "green";
  if (s.startsWith("disabled") || s === "not_started") return "gray";
  if (s.startsWith("standby")) return "amber";
  return "red";
}

export function HealthSummary() {
  const { data } = usePoll<Health>("/health", 20000);
  if (!data) return null;
  const idx = data.indexer || {};
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <Badge tone={statusTone(data.service.status)}>service {data.service.status}</Badge>
      {idx.mode !== undefined && <Badge tone={idx.mode === "live" ? "green" : "amber"}>indexer {String(idx.mode)}</Badge>}
      {idx.lag_s !== undefined && <Badge tone={Number(idx.lag_s) > 90 ? "red" : "gray"}>lag {String(idx.lag_s)}s</Badge>}
      {data.storage?.pct !== undefined && <Badge tone={(data.storage.pct ?? 0) >= 70 ? "red" : "gray"}>db {data.storage.pct}%</Badge>}
    </div>
  );
}

export default function HealthPanel() {
  const { data, error, loading } = usePoll<Health>("/health", 15000);
  if (loading && !data) return <Loading />;
  if (!data) return <ErrorNote error={error} />;
  const idx = data.indexer || {};
  const sources = Object.entries(data.sources || {});
  const notRunningHere = data.service.status === "disabled" || data.service.status === "not_started";
  return (
    <div className="space-y-4">
      <ErrorNote error={error} />
      {notRunningHere && (
        <Card>
          <p className="text-sm">
            The RHC service is <b>{data.service.status}</b> in this backend process. If it runs as a separate process
            (e.g. <code className={mono}>python rhc_indexer.py run</code>), live indexer metrics are only visible there;
            stored data (watchlist, candles, decisions) still shows on the other tabs.
          </p>
        </Card>
      )}
      <Card title="Service" right={<Badge tone={statusTone(data.service.status)}>{data.service.status}</Badge>}>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-4">
          <Stat label="Mode" value={data.mode} sub={`live trading ${data.live_trading}`} />
          <Stat label="Writer lease" value={data.service.lock_held ? "held" : "no"} />
          <Stat label="Indexer" value={String(idx.mode ?? "—")} sub={`lag ${fmtNum(idx.lag_s)} s · ${fmtNum(idx.lag_blocks)} blocks`}
            tone={Number(idx.lag_s) > 90 ? "bad" : undefined} />
          <Stat label="Processed block" value={fmtNum(idx.processed_block)} sub={`head ${fmtNum(idx.head)}`} />
          <Stat label="Tracked pools" value={fmtNum(idx.tracked_pools)} sub={`trades ${fmtNum(idx.trades)}`} />
          <Stat label="ETH / USD" value={idx.eth_usd ? `$${Number(idx.eth_usd).toFixed(2)}` : "—"} />
          <Stat label="Candles written" value={fmtNum(idx.candles_written)} sub={`reorgs ${fmtNum(idx.reorgs)}`} />
          <Stat label="Storage" value={data.storage?.size_mb !== undefined ? `${data.storage.size_mb} MB` : "—"}
            sub={data.storage ? `${data.storage.pct}% of ${data.storage.budget_mb} MB · ${data.storage.level}` : undefined}
            tone={(data.storage?.pct ?? 0) >= 70 ? "bad" : undefined} />
          <Stat label="Screener" value={fmtNum(data.screener?.screened)}
            sub={`passed ${fmtNum(data.screener?.passed)} · rejected ${fmtNum(data.screener?.rejected)}`} />
          <Stat label="Decisions" value={fmtNum(data.decisions?.decisions)} sub={`broker ${String(data.decisions?.broker ?? "—")}`} />
          <Stat label="Regime" value={data.regime?.label ?? "—"} sub={`ETH 1h ${fmtPct(data.regime?.eth_ret_1h ?? null)}`} />
          <Stat label="Pools / tokens" value={`${fmtNum(data.counts?.pools)} / ${fmtNum(data.counts?.tokens)}`} sub={`candles ${fmtNum(data.counts?.candles)}`} />
        </div>
        {Boolean(data.service.error || idx.last_error) && (
          <div className="mt-3 text-xs text-[var(--color-text-secondary)] break-words">
            Last error: {String(data.service.error || idx.last_error)} {idx.last_error_at ? `(${ago(Number(idx.last_error_at))})` : ""}
          </div>
        )}
      </Card>
      <Card title="Data sources">
        <Table empty={sources.length === 0} head={["Source", "OK", "Errors", "Latency", "Last OK", "Last error"]}>
          {sources.map(([name, s]) => (
            <tr key={name} className={tr}>
              <td className={`${td} font-semibold`}>{name}</td>
              <td className={`${td} ${mono}`}>{fmtNum(s.ok_count)}</td>
              <td className={`${td} ${mono}`}>{fmtNum(s.err_count)}</td>
              <td className={`${td} ${mono}`}>{s.last_latency_ms ? `${s.last_latency_ms} ms` : "—"}</td>
              <td className={`${td} ${mono}`}>{ago(Number(s.last_ok_ts) || null)}</td>
              <td className={`${td} text-xs text-[var(--color-text-secondary)] break-all`}>{String(s.last_err ?? "—")}</td>
            </tr>
          ))}
        </Table>
        {data.rpc && (
          <div className="text-xs text-[var(--color-text-secondary)] mt-3">
            RPC endpoints: {data.rpc.urls} (active #{data.rpc.active_url_index}) ·{" "}
            {data.rpc.per_url.map((u, i) => `#${i}: ${fmtNum(u.ok)} ok / ${fmtNum(u.err)} err, ${fmtNum(u.latency_ms)} ms`).join(" · ")}
          </div>
        )}
        {data.cross_check?.flagged && data.cross_check.flagged.length > 0 && (
          <div className="text-xs mt-2">
            Persistent price disagreements: {data.cross_check.flagged.map((f) => `pool ${f.pool_pk} vs ${f.source} ${f.dev_pct}%`).join(" · ")}
          </div>
        )}
      </Card>
    </div>
  );
}
