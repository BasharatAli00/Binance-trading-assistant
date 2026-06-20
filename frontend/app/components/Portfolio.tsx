'use client';
import { useEffect, useState } from 'react';

import API_URL from "@/lib/config";

interface PortfolioData {
  USDT: number;
  BTC: number;
  cash: number;
  total_equity: number;
  positions_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  total_pnl_pct: number;
  starting_balance: number;
  btc_avg_entry: number;
  btc_value: number;
}

const fmtUsd = (n: number) =>
  `$${(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function Pnl({ value, pct }: { value: number; pct?: number }) {
  const positive = (value || 0) >= 0;
  const color = positive ? 'text-[#0ECB81]' : 'text-[#F6465D]';
  const sign = positive ? '+' : '';
  return (
    <span className={`font-bold ${color}`}>
      {sign}{fmtUsd(value)}{pct !== undefined ? ` (${sign}${(pct || 0).toFixed(2)}%)` : ''}
    </span>
  );
}

export default function Portfolio() {
  const [data, setData] = useState<PortfolioData | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/balance`);
        const d = await res.json();
        setData(d);
      } catch (err) {
        console.error("Error fetching portfolio data", err);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const equity = data?.total_equity ?? 0;
  const totalPnl = data?.total_pnl ?? 0;
  const pnlPct = data?.total_pnl_pct ?? 0;

  return (
    <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-6 rounded-lg shadow-lg">
      <div className="flex justify-between items-center mb-4">
        <div className="text-[color:var(--color-text-secondary)] text-sm font-medium uppercase">Portfolio (Demo)</div>
        <div className="text-[10px] text-[color:var(--color-text-secondary)] uppercase">Paper · Live Prices</div>
      </div>

      <div className="mb-5">
        <div className="text-[color:var(--color-text-secondary)] text-xs uppercase mb-1">Total Equity</div>
        <div className="text-3xl font-bold text-[color:var(--color-text-primary)]">{fmtUsd(equity)}</div>
        <div className="text-sm mt-1">
          <Pnl value={totalPnl} pct={pnlPct} />
          <span className="text-[color:var(--color-text-secondary)] text-xs ml-2">vs {fmtUsd(data?.starting_balance ?? 5000)} start</span>
        </div>
      </div>

      {/* P&L breakdown */}
      <div className="grid grid-cols-2 gap-3 mb-5">
        <div className="bg-[var(--color-bg-panel)] rounded p-3 border border-[var(--color-border)]">
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase mb-1">Unrealized P&L</div>
          <div className="text-sm"><Pnl value={data?.unrealized_pnl ?? 0} /></div>
        </div>
        <div className="bg-[var(--color-bg-panel)] rounded p-3 border border-[var(--color-border)]">
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase mb-1">Realized P&L</div>
          <div className="text-sm"><Pnl value={data?.realized_pnl ?? 0} /></div>
        </div>
      </div>

      {/* Holdings */}
      <div className="space-y-3">
        <div className="flex justify-between items-center pb-2 border-b border-[var(--color-border)]">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full flex items-center justify-center font-bold text-xs"
                 style={{ backgroundColor: '#0ECB8133', color: '#0ECB81' }}>U</div>
            <span className="text-[color:var(--color-text-secondary)] font-medium">USDT (Cash)</span>
          </div>
          <span className="text-[color:var(--color-text-primary)] font-bold">{fmtUsd(data?.cash ?? 0)}</span>
        </div>

        <div className="flex justify-between items-center">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full flex items-center justify-center font-bold text-xs"
                 style={{ backgroundColor: '#F7931A33', color: '#F7931A' }}>B</div>
            <div>
              <span className="text-[color:var(--color-text-secondary)] font-medium">BTC</span>
              {(data?.BTC ?? 0) > 0 && (
                <div className="text-[10px] text-[color:var(--color-text-secondary)]">avg entry {fmtUsd(data?.btc_avg_entry ?? 0)}</div>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[color:var(--color-text-primary)] font-bold">{(data?.BTC ?? 0).toFixed(6)}</div>
            <div className="text-[10px] text-[color:var(--color-text-secondary)]">{fmtUsd(data?.btc_value ?? 0)}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
