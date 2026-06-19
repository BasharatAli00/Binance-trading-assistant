'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

type FuturesData = {
  symbol: string;
  long_pct: number;
  short_pct: number;
  long_short_ratio: number;
  funding_rate: number;          // fraction, e.g. 0.0001 = 0.01%
  funding_direction: string;     // "Longs pay" / "Shorts pay" / "Neutral"
  next_funding_time: string | null;
  timestamp: string;
};

const fmt = (v: number | null | undefined, d = 1) =>
  v == null ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

// Funding rate shown as a percentage with 4 decimals (rates are tiny).
const fundingPct = (v: number | null | undefined) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(4)}%`;

export default function FuturesCard({ symbol }: { symbol: string }) {
  const [data, setData] = useState<FuturesData | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    setData(null);
    setMissing(false);
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/futures?symbol=${symbol}`);
        if (res.status === 404) { setMissing(true); return; }
        const result = await res.json();
        if (!result.error) { setData(result); setMissing(false); }
      } catch (err) {
        console.error("Error fetching futures stats", err);
      }
    };
    fetchData();
    // Backend refreshes hourly; poll every 5 min.
    const interval = setInterval(fetchData, 300000);
    return () => clearInterval(interval);
  }, [symbol]);

  if (missing) {
    return (
      <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-gray-400 text-sm font-bold font-sans mb-2">FUTURES SENTIMENT</div>
        <div className="text-gray-500 text-sm">No data yet — collected hourly.</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-gray-400 text-sm font-bold font-sans mb-2">FUTURES SENTIMENT</div>
        <div className="text-gray-500 text-sm">Loading…</div>
      </div>
    );
  }

  const longPct = Math.max(0, Math.min(100, data.long_pct ?? 0));
  const shortPct = Math.max(0, Math.min(100, data.short_pct ?? 0));
  // Positive funding = longs pay (bullish crowd / costlier longs) -> red-ish warning;
  // negative = shorts pay -> green-ish. Neutral gray.
  const fundingColor = (data.funding_rate ?? 0) > 0 ? '#ff6b81'
    : (data.funding_rate ?? 0) < 0 ? '#00ff88' : '#9ca3af';
  const updated = data.timestamp
    ? new Date(data.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';
  const nextFunding = data.next_funding_time
    ? new Date(data.next_funding_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg hover:border-gray-500 transition-colors">
      <div className="flex justify-between items-center mb-3">
        <span className="text-gray-400 text-sm font-bold font-sans">FUTURES SENTIMENT</span>
        <span className="text-xs text-gray-500">{symbol.replace('USDT', '/USDT')}{updated && ` · ${updated}`}</span>
      </div>

      {/* Long / Short account ratio */}
      <div className="mb-1 flex justify-between text-[11px] uppercase tracking-wide">
        <span className="text-[#00ff88]">Long {fmt(longPct)}%</span>
        <span className="text-[#ff4466]">Short {fmt(shortPct)}%</span>
      </div>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-[#1c1c1c]">
        <div style={{ width: `${longPct}%`, backgroundColor: '#00ff88' }} />
        <div style={{ width: `${shortPct}%`, backgroundColor: '#ff4466' }} />
      </div>
      <div className="mt-1 text-[10px] text-gray-500 text-right">
        L/S ratio {fmt(data.long_short_ratio, 2)}
      </div>

      {/* Funding rate */}
      <div className="mt-3 pt-3 border-t border-[#222222] flex justify-between items-center">
        <div className="flex flex-col">
          <span className="text-gray-500 text-[10px] uppercase">Funding Rate</span>
          <span className="text-[10px] text-gray-500">{data.funding_direction}</span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-lg font-bold" style={{ color: fundingColor }}>{fundingPct(data.funding_rate)}</span>
          {nextFunding && <span className="text-[10px] text-gray-500">next {nextFunding}</span>}
        </div>
      </div>
    </div>
  );
}
