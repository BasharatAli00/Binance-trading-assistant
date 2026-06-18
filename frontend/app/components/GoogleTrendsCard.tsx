'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

type TrendData = {
  keyword: string;
  trend_score: number | null;
  prev_score: number | null;
  wow_change_pct: number | null;
  timestamp: string;
};

const fmt = (v: number | null, d = 0) =>
  v == null ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

export default function GoogleTrendsCard() {
  const [data, setData] = useState<TrendData | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/trends`);
        if (res.status === 404) { setMissing(true); return; }
        const result = await res.json();
        if (!result.error) { setData(result); setMissing(false); }
      } catch (err) {
        console.error("Error fetching Google Trends", err);
      }
    };
    fetchData();
    // Updates at most daily; poll loosely.
    const interval = setInterval(fetchData, 600000);
    return () => clearInterval(interval);
  }, []);

  if (missing) {
    return (
      <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-gray-400 text-sm font-bold font-sans mb-2">GOOGLE TRENDS</div>
        <div className="text-gray-500 text-sm">No data yet — collecting…</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-gray-400 text-sm font-bold font-sans mb-2">GOOGLE TRENDS</div>
        <div className="text-gray-500 text-sm">Loading…</div>
      </div>
    );
  }

  const wow = data.wow_change_pct ?? 0;
  const up = wow >= 0;
  const color = up ? '#00ff88' : '#ff4466';
  const updated = data.timestamp
    ? new Date(data.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : '';

  return (
    <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg hover:border-gray-500 transition-colors">
      <div className="flex justify-between items-center mb-3">
        <span className="text-gray-400 text-sm font-bold font-sans">GOOGLE TRENDS</span>
        <span className="text-xs text-gray-500">&quot;Bitcoin&quot;{updated && ` · ${updated}`}</span>
      </div>

      <div className="flex items-end gap-3">
        <div className="text-4xl font-bold text-white">{fmt(data.trend_score)}</div>
        <div className="pb-1">
          <div className="text-sm font-bold" style={{ color }}>
            {up ? '▲' : '▼'} {up ? '+' : ''}{wow.toFixed(1)}%
          </div>
          <div className="text-xs text-gray-500">week over week</div>
        </div>
      </div>

      <div className="text-[10px] text-gray-600 mt-3">
        Search interest 0–100 · prev week {fmt(data.prev_score)}
      </div>
    </div>
  );
}
