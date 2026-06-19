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

type Wallet = {
  total_equity: number;
  total_pnl: number;
  total_pnl_pct: number;
};

const usd = (n: number | undefined) =>
  `$${(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const pct = (n: number | undefined) =>
  `${(n || 0) >= 0 ? '+' : ''}${(n || 0).toFixed(2)}%`;
const pnlColor = (n: number | undefined) => ((n || 0) >= 0 ? '#00ff88' : '#ff4466');

function trendColor(trend: string) {
  if (trend === 'Uptrend') return '#00ff88';
  if (trend === 'Downtrend') return '#ff4466';
  return '#9ca3af';
}

// One side of the head-to-head race strip.
function RaceSide({ label, wallet, leading }: { label: string; wallet: Wallet | null; leading: boolean }) {
  return (
    <div className={`flex-1 rounded-md p-2 ${leading ? 'bg-[#16241c] border border-[#1f3a2a]' : 'bg-[#1a1a1a] border border-[#222222]'}`}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase text-gray-400">{label}</span>
        {leading && <span className="text-[9px] text-[#00ff88]">▲ leading</span>}
      </div>
      <div className="text-sm font-bold text-white">{usd(wallet?.total_equity)}</div>
      <div className="text-[11px] font-bold" style={{ color: pnlColor(wallet?.total_pnl_pct) }}>
        {pct(wallet?.total_pnl_pct)} <span className="text-gray-500 font-normal">({usd(wallet?.total_pnl)})</span>
      </div>
    </div>
  );
}

export default function PivotStrategyCard({ symbol }: { symbol: string }) {
  const [d, setD] = useState<PivotState | null>(null);
  const [core, setCore] = useState<Wallet | null>(null);    // strategy #1 wallet
  const [pivot, setPivot] = useState<Wallet | null>(null);  // strategy #2 wallet

  useEffect(() => {
    setD(null);
    const fetchData = async () => {
      try {
        const [sRes, cRes, pRes] = await Promise.all([
          fetch(`${API_URL}/api/pivot-strategy?symbol=${symbol}`),
          fetch(`${API_URL}/api/portfolio`),
          fetch(`${API_URL}/api/pivot-portfolio`),
        ]);
        const s = await sRes.json();
        if (!s.error) setD(s);
        const c = await cRes.json();
        if (!c.error) setCore(c);
        const p = await pRes.json();
        if (!p.error) setPivot(p);
      } catch (err) {
        console.error("Error fetching pivot strategy", err);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  if (!d) {
    return (
      <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-gray-400 text-sm font-bold font-sans mb-2">STRATEGY #2 · PIVOT BRACKET</div>
        <div className="text-gray-500 text-sm">Loading…</div>
      </div>
    );
  }

  const inPos = d.in_position;
  const statusColor = inPos ? '#00ff88' : '#888888';
  // Leader = higher total P&L %. Ties / missing data -> no badge.
  const corePnl = core?.total_pnl_pct;
  const pivotPnl = pivot?.total_pnl_pct;
  const coreLeads = corePnl != null && pivotPnl != null && corePnl > pivotPnl;
  const pivotLeads = corePnl != null && pivotPnl != null && pivotPnl > corePnl;

  return (
    <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg hover:border-gray-500 transition-colors">
      <div className="flex justify-between items-center mb-3">
        <span className="text-gray-400 text-sm font-bold font-sans">STRATEGY #2 · PIVOT BRACKET</span>
        <span className="text-xs font-bold" style={{ color: statusColor }}>
          {inPos ? '● IN POSITION' : '○ FLAT'}
        </span>
      </div>

      {/* Head-to-head wallet race */}
      <div className="flex gap-2 mb-3">
        <RaceSide label="#1 Trend" wallet={core} leading={coreLeads} />
        <RaceSide label="#2 Pivot" wallet={pivot} leading={pivotLeads} />
      </div>

      {/* Live bracket */}
      {inPos ? (
        <div className="grid grid-cols-3 gap-3 mb-3">
          <div>
            <div className="text-gray-500 text-[10px] uppercase">Entry</div>
            <div className="text-white text-sm font-bold">{usd(d.entry_price)}</div>
          </div>
          <div>
            <div className="text-gray-500 text-[10px] uppercase">Target (R1)</div>
            <div className="text-[#00ff88] text-sm font-bold">{usd(d.take_profit)}</div>
          </div>
          <div>
            <div className="text-gray-500 text-[10px] uppercase">Stop (S1)</div>
            <div className="text-[#ff4466] text-sm font-bold">{usd(d.stop_price)}</div>
          </div>
        </div>
      ) : (
        <div className="text-gray-400 text-sm mb-3">Scanning for a pivot setup…</div>
      )}

      {/* Pivot context */}
      <div className="grid grid-cols-3 gap-3 pt-3 border-t border-[#222222] text-center">
        <div>
          <div className="text-gray-500 text-[10px] uppercase">Pivot</div>
          <div className="text-sm font-bold text-yellow-500">{usd(d.pp)}</div>
        </div>
        <div>
          <div className="text-gray-500 text-[10px] uppercase">Trend</div>
          <div className="text-sm font-bold" style={{ color: trendColor(d.trend) }}>{d.trend || '—'}</div>
        </div>
        <div>
          <div className="text-gray-500 text-[10px] uppercase">R1 / S1</div>
          <div className="text-[11px] font-bold">
            <span className="text-[#00ff88]">{Math.round(d.r1).toLocaleString()}</span>
            <span className="text-gray-600"> / </span>
            <span className="text-[#ff4466]">{Math.round(d.s1).toLocaleString()}</span>
          </div>
        </div>
      </div>

      <div className="text-[11px] text-gray-500 mt-3 leading-snug">{d.message}</div>
    </div>
  );
}
