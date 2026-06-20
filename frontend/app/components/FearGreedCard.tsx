'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

type FngData = { value: number | null; classification: string | null; fetched_at: number };

// Color the gauge by zone: red = fear, green = greed, amber = neutral.
function zoneColor(v: number) {
  if (v <= 24) return '#ff4466';      // Extreme Fear
  if (v <= 44) return '#ff8800';      // Fear
  if (v <= 54) return '#ffbb00';      // Neutral
  if (v <= 74) return '#88cc00';      // Greed
  return '#00ff88';                   // Extreme Greed
}

export default function FearGreedCard() {
  const [data, setData] = useState<FngData | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/feargreed`);
        const result = await res.json();
        setData(result);
      } catch (err) {
        console.error("Error fetching fear & greed", err);
      }
    };
    fetchData();
    // It only changes once a day; poll loosely just to pick up the daily flip.
    const interval = setInterval(fetchData, 300000);
    return () => clearInterval(interval);
  }, []);

  if (!data || data.value == null) {
    return (
      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-[color:var(--color-text-secondary)] text-sm font-bold font-sans mb-2">FEAR &amp; GREED</div>
        <div className="text-[color:var(--color-text-secondary)] text-sm">Loading sentiment…</div>
      </div>
    );
  }

  const v = data.value;
  const color = zoneColor(v);
  const updated = data.fetched_at
    ? new Date(data.fetched_at * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : '';

  return (
    <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg p-4 font-mono shadow-lg hover:border-gray-500 transition-colors">
      <div className="flex justify-between items-center mb-3">
        <span className="text-[color:var(--color-text-secondary)] text-sm font-bold font-sans">FEAR &amp; GREED</span>
        <span className="text-xs text-[color:var(--color-text-secondary)]">Market-wide{updated && ` · ${updated}`}</span>
      </div>

      <div className="flex items-end gap-3">
        <div className="text-4xl font-bold" style={{ color }}>{v}</div>
        <div className="pb-1">
          <div className="text-sm font-bold" style={{ color }}>{data.classification}</div>
          <div className="text-xs text-[color:var(--color-text-secondary)]">out of 100</div>
        </div>
      </div>

      {/* Gauge: full fear→greed spectrum with a marker at the current value */}
      <div className="relative w-full h-2 rounded mt-4"
           style={{ background: 'linear-gradient(90deg,#ff4466 0%,#ff8800 25%,#ffbb00 50%,#88cc00 75%,#00ff88 100%)' }}>
        <div className="absolute h-4 w-1.5 bg-white rounded -top-1 shadow shadow-black"
             style={{ left: `${Math.min(100, Math.max(0, v))}%`, transform: 'translateX(-50%)' }} />
      </div>
      <div className="flex justify-between text-[10px] text-gray-600 mt-1">
        <span>Fear</span>
        <span>Neutral</span>
        <span>Greed</span>
      </div>
    </div>
  );
}
