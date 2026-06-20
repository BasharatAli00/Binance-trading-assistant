'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

type StrategyState = {
  symbol: string;
  price: number;
  signal: string;
  message: string;
  in_position: boolean;
  entry_price: number;
  stop_price: number;
  unrealized_r: number;
  adx: number;
  atr: number;
  rsi: number;
  ema200: number;
};

const usd = (n: number) => `$${(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export default function StrategyCard({ symbol }: { symbol: string }) {
  const [d, setD] = useState<StrategyState | null>(null);

  useEffect(() => {
    setD(null);
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/strategy?symbol=${symbol}`);
        const result = await res.json();
        if (!result.error) setD(result);
      } catch (err) {
        console.error("Error fetching strategy", err);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  if (!d) {
    return (
      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-[color:var(--color-text-secondary)] text-sm font-bold font-sans mb-2">STRATEGY</div>
        <div className="text-[color:var(--color-text-secondary)] text-sm">Loading…</div>
      </div>
    );
  }

  const inPos = d.in_position;
  const rColor = d.unrealized_r >= 0 ? '#00ff88' : '#ff4466';
  const statusColor = inPos ? '#00ff88' : '#888888';

  return (
    <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg p-4 font-mono shadow-lg hover:border-gray-500 transition-colors">
      <div className="flex justify-between items-center mb-3">
        <span className="text-[color:var(--color-text-secondary)] text-sm font-bold font-sans">STRATEGY · TREND-FOLLOW</span>
        <span className="text-xs font-bold" style={{ color: statusColor }}>
          {inPos ? '● IN POSITION' : '○ FLAT'}
        </span>
      </div>

      {inPos ? (
        <div className="grid grid-cols-3 gap-3 mb-3">
          <div>
            <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase">Entry</div>
            <div className="text-[color:var(--color-text-primary)] text-sm font-bold">{usd(d.entry_price)}</div>
          </div>
          <div>
            <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase">Stop / Trail</div>
            <div className="text-[#ff8800] text-sm font-bold">{usd(d.stop_price)}</div>
          </div>
          <div>
            <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase">Open P&L</div>
            <div className="text-sm font-bold" style={{ color: rColor }}>
              {d.unrealized_r >= 0 ? '+' : ''}{d.unrealized_r.toFixed(2)}R
            </div>
          </div>
        </div>
      ) : (
        <div className="text-[color:var(--color-text-secondary)] text-sm mb-3">Scanning for a trend setup…</div>
      )}

      <div className="grid grid-cols-3 gap-3 pt-3 border-t border-[var(--color-border)] text-center">
        <div>
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase">ADX</div>
          <div className={`text-sm font-bold ${d.adx >= 35 ? 'text-[#00ff88]' : 'text-[color:var(--color-text-secondary)]'}`}>{d.adx.toFixed(0)}</div>
        </div>
        <div>
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase">RSI</div>
          <div className="text-sm font-bold text-[color:var(--color-text-secondary)]">{d.rsi.toFixed(0)}</div>
        </div>
        <div>
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase">vs EMA200</div>
          <div className={`text-sm font-bold ${d.price > d.ema200 ? 'text-[#00ff88]' : 'text-[#ff4466]'}`}>
            {d.price > d.ema200 ? 'ABOVE' : 'BELOW'}
          </div>
        </div>
      </div>

      <div className="text-[11px] text-[color:var(--color-text-secondary)] mt-3 leading-snug">{d.message}</div>
    </div>
  );
}
