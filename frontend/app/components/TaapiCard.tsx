'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

type TaapiData = {
  symbol: string;
  rsi: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
  ema20: number | null;
  timestamp: string;
};

// RSI color: green oversold (<30), red overbought (>70), white otherwise.
function rsiColor(v: number | null) {
  if (v == null) return '#e5e7eb';
  if (v < 30) return '#00ff88';
  if (v > 70) return '#ff4466';
  return '#ffffff';
}

const fmt = (v: number | null, d = 2) =>
  v == null ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

export default function TaapiCard({ symbol }: { symbol: string }) {
  const [data, setData] = useState<TaapiData | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    setData(null);
    setMissing(false);
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/taapi?symbol=${symbol}`);
        if (res.status === 404) { setMissing(true); return; }
        const result = await res.json();
        if (!result.error) { setData(result); setMissing(false); }
      } catch (err) {
        console.error("Error fetching Taapi indicators", err);
      }
    };
    fetchData();
    // Backend caches 15 min; poll loosely.
    const interval = setInterval(fetchData, 300000);
    return () => clearInterval(interval);
  }, [symbol]);

  if (missing) {
    return (
      <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-gray-400 text-sm font-bold font-sans mb-2">TAAPI.IO INDICATORS</div>
        <div className="text-gray-500 text-sm">No data yet — set TAAPI_API_KEY to enable.</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-gray-400 text-sm font-bold font-sans mb-2">TAAPI.IO INDICATORS</div>
        <div className="text-gray-500 text-sm">Loading…</div>
      </div>
    );
  }

  const macdAbove = data.macd != null && data.macd_signal != null && data.macd > data.macd_signal;
  const updated = data.timestamp
    ? new Date(data.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  return (
    <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg hover:border-gray-500 transition-colors">
      <div className="flex justify-between items-center mb-3">
        <span className="text-gray-400 text-sm font-bold font-sans">TAAPI.IO INDICATORS</span>
        <span className="text-xs text-gray-500">{symbol.replace('USDT', '/USDT')}{updated && ` · ${updated}`}</span>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="flex flex-col gap-1">
          <div className="text-gray-500 text-[10px] uppercase">RSI (1h)</div>
          <div className="text-2xl font-bold" style={{ color: rsiColor(data.rsi) }}>{fmt(data.rsi)}</div>
        </div>
        <div className="flex flex-col gap-1">
          <div className="text-gray-500 text-[10px] uppercase">MACD</div>
          <div className="text-lg font-bold" style={{ color: macdAbove ? '#00ff88' : '#ff4466' }}>{fmt(data.macd)}</div>
          <div className="text-[10px] text-gray-500">sig {fmt(data.macd_signal)}</div>
        </div>
        <div className="flex flex-col gap-1">
          <div className="text-gray-500 text-[10px] uppercase">EMA 20</div>
          <div className="text-lg font-bold text-white">${fmt(data.ema20)}</div>
        </div>
      </div>
    </div>
  );
}
