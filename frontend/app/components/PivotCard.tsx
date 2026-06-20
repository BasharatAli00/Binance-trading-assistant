'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

type PivotData = {
  symbol: string;
  pp: number;
  r1: number; r2: number; r3: number;
  s1: number; s2: number; s3: number;
  trend: string;
  timestamp: string;
};

const fmt = (v: number | null | undefined, d = 2) =>
  v == null ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

// Trend badge colors: green up, red down, gray neutral.
function trendStyle(trend: string) {
  if (trend === 'Uptrend') return { color: '#00ff88', bg: 'rgba(0,255,136,0.1)' };
  if (trend === 'Downtrend') return { color: '#ff4466', bg: 'rgba(255,68,102,0.1)' };
  return { color: '#9ca3af', bg: 'rgba(156,163,175,0.1)' };
}

// One row in the support/resistance ladder.
function Level({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex justify-between items-center py-1 px-2 rounded">
      <span className="text-[11px] uppercase tracking-wide" style={{ color }}>{label}</span>
      <span className="text-sm font-bold" style={{ color }}>${fmt(value)}</span>
    </div>
  );
}

export default function PivotCard({ symbol }: { symbol: string }) {
  const [data, setData] = useState<PivotData | null>(null);
  const [price, setPrice] = useState<number | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    setData(null);
    setPrice(null);
    setMissing(false);

    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/pivots?symbol=${symbol}`);
        if (res.status === 404) { setMissing(true); return; }
        const result = await res.json();
        if (!result.error) { setData(result); setMissing(false); }
      } catch (err) {
        console.error("Error fetching pivot levels", err);
      }
      try {
        const pres = await fetch(`${API_URL}/api/price?symbol=${symbol}`);
        const pjson = await pres.json();
        if (pjson && typeof pjson.price === 'number') setPrice(pjson.price);
      } catch { /* price marker is optional */ }
    };

    fetchData();
    // Pivots only change once a day; price drifts — poll loosely.
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [symbol]);

  if (missing) {
    return (
      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-[color:var(--color-text-secondary)] text-sm font-bold font-sans mb-2">PIVOT LEVELS (DAILY)</div>
        <div className="text-[color:var(--color-text-secondary)] text-sm">No data yet — collected daily after 00:25 UTC.</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-[color:var(--color-text-secondary)] text-sm font-bold font-sans mb-2">PIVOT LEVELS (DAILY)</div>
        <div className="text-[color:var(--color-text-secondary)] text-sm">Loading…</div>
      </div>
    );
  }

  const ts = trendStyle(data.trend);
  const updated = data.timestamp
    ? new Date(data.timestamp).toLocaleDateString([], { month: 'short', day: 'numeric' })
    : '';

  return (
    <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg p-4 font-mono shadow-lg hover:border-gray-500 transition-colors">
      <div className="flex justify-between items-center mb-3">
        <span className="text-[color:var(--color-text-secondary)] text-sm font-bold font-sans">PIVOT LEVELS (DAILY)</span>
        <span
          className="text-[11px] font-bold px-2 py-0.5 rounded"
          style={{ color: ts.color, backgroundColor: ts.bg }}
        >
          {data.trend}
        </span>
      </div>

      {/* Resistances (red, high -> low) */}
      <div className="flex flex-col gap-0.5">
        <Level label="Resistance 3" value={data.r3} color="#ff4466" />
        <Level label="Resistance 2" value={data.r2} color="#ff4466" />
        <Level label="Resistance 1" value={data.r1} color="#ff6b81" />
      </div>

      {/* Current price + pivot point in the middle */}
      <div className="my-2 border-y border-[var(--color-border)] py-2 flex flex-col gap-0.5">
        {price != null && (
          <div className="flex justify-between items-center py-1 px-2">
            <span className="text-[11px] uppercase tracking-wide text-[color:var(--color-text-secondary)]">Price</span>
            <span className="text-sm font-bold text-[color:var(--color-text-primary)]">${fmt(price)}</span>
          </div>
        )}
        <div className="flex justify-between items-center py-1 px-2">
          <span className="text-[11px] uppercase tracking-wide text-yellow-500">Pivot (PP)</span>
          <span className="text-sm font-bold text-yellow-500">${fmt(data.pp)}</span>
        </div>
      </div>

      {/* Supports (green, high -> low) */}
      <div className="flex flex-col gap-0.5">
        <Level label="Support 1" value={data.s1} color="#34d399" />
        <Level label="Support 2" value={data.s2} color="#00ff88" />
        <Level label="Support 3" value={data.s3} color="#00ff88" />
      </div>

      {updated && <div className="text-[10px] text-gray-600 mt-2 text-right">from {updated} close</div>}
    </div>
  );
}
