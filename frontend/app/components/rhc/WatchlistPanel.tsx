"use client";

import { useState } from "react";
import { ago, codes, fmtNum, shortAddr, usePoll, type WatchRow } from "./api";
import { Badge, Card, Chips, ErrorNote, Loading, StateBadge, Table, mono, td, tr } from "./ui";

const STATES = ["watch", "candidate", "rejected", "expired"] as const;

export default function WatchlistPanel({ onSelect, compact = false, fixedState }: {
  onSelect: (poolId: string) => void;
  compact?: boolean;
  fixedState?: (typeof STATES)[number];
}) {
  const [state, setState] = useState<(typeof STATES)[number] | "all">(fixedState ?? "watch");
  const q = state === "all" ? "" : `?state=${state}`;
  const { data, error, loading } = usePoll<WatchRow[]>(`/watchlist${q}${q ? "&" : "?"}limit=${compact ? 8 : 200}`, 20000);
  const rows = data ?? [];

  return (
    <Card
      title={compact ? "Ranked opportunities (watch-listed, by score)" : "Discovered tokens & watchlist"}
      right={!fixedState && (
        <div className="flex flex-wrap gap-1">
          {(["all", ...STATES] as const).map((s) => (
            <button key={s} onClick={() => setState(s)}
              className={`text-xs px-2 py-1 rounded border ${state === s ? "border-[var(--color-brand)] text-[var(--color-brand)]" : "border-[var(--color-border)] text-[var(--color-text-secondary)]"}`}>
              {s}
            </button>
          ))}
        </div>
      )}
    >
      <ErrorNote error={error} />
      {loading && !data ? <Loading /> : (
        <Table empty={rows.length === 0}
          head={compact ? ["Token", "State", "Score", "Discovered by", "Warnings"]
            : ["Token", "Pool", "State", "Score", "Discovered by", "Reject codes", "Warnings", "Screens", "Last screened", "Last trade"]}>
          {rows.map((r) => (
            <tr key={r.pool_pk} className={`${tr} cursor-pointer`} onClick={() => onSelect(r.pool_id)}>
              <td className={`${td} font-semibold`}>{r.symbol || shortAddr(r.token)}</td>
              {!compact && <td className={`${td} ${mono}`}>{r.kind} {shortAddr(r.pool_id)}</td>}
              <td className={td}><StateBadge state={r.state} /></td>
              <td className={`${td} ${mono}`}>{fmtNum(r.score, 2)}</td>
              <td className={td}>
                <div className="flex flex-wrap gap-1">{codes(r.discovery).map((d) => <Badge key={d}>{d}</Badge>)}</div>
              </td>
              {!compact && <td className={td}><Chips list={codes(r.reject_codes)} /></td>}
              <td className={td}><Chips list={codes(r.warn_codes)} /></td>
              {!compact && <td className={`${td} ${mono}`}>{r.screens ?? 0}</td>}
              {!compact && <td className={`${td} ${mono}`}>{ago(r.last_screened_ts)}</td>}
              {!compact && <td className={`${td} ${mono}`}>{ago(r.last_activity_ts)}</td>}
            </tr>
          ))}
        </Table>
      )}
      <p className="text-xs text-[var(--color-text-secondary)] mt-2">
        Click a row for the full token intelligence report. Hover a code for its meaning.
      </p>
    </Card>
  );
}
