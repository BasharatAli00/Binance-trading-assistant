'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

type PivotState = {
  symbol: string;
  signal: string;
  message: string;
  in_position: boolean;
  entry_price: number;
  take_profit: number;
  stop_price: number;
  pp: number;
  r1: number;
  s1: number;
  trend: string;
};

const usd = (n: number | undefined) =>
  `$${(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

function signalStyle(signal: string) {
  if (signal === 'BUY') return { color: '#0ECB81', bg: '#0ECB8122', label: 'BUY' };
  if (signal === 'SELL') return { color: '#F6465D', bg: '#F6465D22', label: 'SELL' };
  return { color: 'var(--color-text-secondary)', bg: 'var(--color-bg-hover)', label: 'HOLD' };
}

function trendColor(trend: string) {
  if (trend === 'Uptrend') return '#0ECB81';
  if (trend === 'Downtrend') return '#F6465D';
  return 'var(--color-text-secondary)';
}

export default function Strategy2Card({ symbol }: { symbol: string }) {
  const [d, setD] = useState<PivotState | null>(null);

  useEffect(() => {
    setD(null);
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/pivot-strategy?symbol=${symbol}`);
        const result = await res.json();
        if (!result.error) setD(result);
      } catch (err) {
        console.error("Error fetching strategy #2", err);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  if (!d) {
    return (
      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-6 rounded-lg shadow-lg">
        <div className="text-[color:var(--color-text-secondary)] text-sm font-medium uppercase mb-2">Strategy #2 · Pivot Bracket</div>
        <div className="text-[color:var(--color-text-secondary)] text-sm">Loading…</div>
      </div>
    );
  }

  const inPos = d.in_position;
  const sig = signalStyle(d.signal);
  const statusColor = inPos ? '#0ECB81' : 'var(--color-text-secondary)';

  return (
    <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-6 rounded-lg shadow-lg">
      <div className="flex justify-between items-center mb-4">
        <span className="text-[color:var(--color-text-secondary)] text-sm font-medium uppercase">Strategy #2 · Pivot Bracket</span>
        <span className="text-xs font-bold" style={{ color: statusColor }}>
          {inPos ? '● IN POSITION' : '○ FLAT'}
        </span>
      </div>

      {/* Signal — the headline for the dashboard */}
      <div className="flex items-center gap-3 mb-4">
        <span
          className="px-3 py-1 rounded-md text-sm font-bold tracking-wide"
          style={{ color: sig.color, backgroundColor: sig.bg }}
        >
          {sig.label}
        </span>
        <span className="text-xs text-[color:var(--color-text-secondary)]">{inPos ? 'holding long' : 'signal'}</span>
      </div>

      {/* Live bracket when in a trade */}
      {inPos ? (
        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="bg-[var(--color-bg-base)] rounded p-3 border border-[var(--color-border)]">
            <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase mb-1">Entry</div>
            <div className="text-[color:var(--color-text-primary)] text-sm font-bold">{usd(d.entry_price)}</div>
          </div>
          <div className="bg-[var(--color-bg-base)] rounded p-3 border border-[var(--color-border)]">
            <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase mb-1">Target (R1)</div>
            <div className="text-[#0ECB81] text-sm font-bold">{usd(d.take_profit)}</div>
          </div>
          <div className="bg-[var(--color-bg-base)] rounded p-3 border border-[var(--color-border)]">
            <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase mb-1">Stop (S1)</div>
            <div className="text-[#F6465D] text-sm font-bold">{usd(d.stop_price)}</div>
          </div>
        </div>
      ) : (
        <div className="text-[color:var(--color-text-secondary)] text-sm mb-4">Scanning for a pivot setup…</div>
      )}

      {/* Pivot context */}
      <div className="grid grid-cols-3 gap-3 pt-4 border-t border-[var(--color-border)] text-center">
        <div>
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase">Pivot</div>
          <div className="text-sm font-bold text-[#f0b90b]">{usd(d.pp)}</div>
        </div>
        <div>
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase">Trend</div>
          <div className="text-sm font-bold" style={{ color: trendColor(d.trend) }}>{d.trend || '—'}</div>
        </div>
        <div>
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase">R1 / S1</div>
          <div className="text-[11px] font-bold">
            <span className="text-[#0ECB81]">{Math.round(d.r1).toLocaleString()}</span>
            <span className="text-[color:var(--color-text-secondary)]"> / </span>
            <span className="text-[#F6465D]">{Math.round(d.s1).toLocaleString()}</span>
          </div>
        </div>
      </div>

      <div className="text-[11px] text-[color:var(--color-text-secondary)] mt-4 leading-snug">{d.message}</div>
      <div className="text-[10px] text-[color:var(--color-text-secondary)] mt-2">P&amp;L and trade history on the Portfolio page → Strategy Two</div>
    </div>
  );
}
