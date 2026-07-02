'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

interface ManualPortfolioData {
  cash: number;
  reserved: number;
  positions_value: number;
  total_equity: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  total_pnl_pct: number;
  starting_balance: number;
  open_positions: number;
  pending_orders: number;
  max_positions: number;
  btc_price: number;
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

export default function ManualPortfolio() {
  const [data, setData] = useState<ManualPortfolioData | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/manual-portfolio`);
        const d = await res.json();
        if (!d.error) setData(d);
      } catch (err) {
        console.error("Error fetching manual portfolio", err);
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
        <div className="text-[color:var(--color-text-secondary)] text-sm font-medium uppercase">Manual Desk (Demo)</div>
        <div className="flex items-center gap-3">
          <div className="text-[11px] text-[color:var(--color-text-secondary)]">
            BTC {fmtUsd(data?.btc_price ?? 0)}
          </div>
          <div className="text-[10px] text-[color:var(--color-text-secondary)] uppercase">Paper · Live Prices</div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
        <div>
          <div className="text-[color:var(--color-text-secondary)] text-xs uppercase mb-1">Total Equity</div>
          <div className="text-3xl font-bold text-[color:var(--color-text-primary)]">{fmtUsd(equity)}</div>
          <div className="text-sm mt-1">
            <Pnl value={totalPnl} pct={pnlPct} />
          </div>
          <div className="text-[10px] text-[color:var(--color-text-secondary)] mt-1">
            vs {fmtUsd(data?.starting_balance ?? 10000)} start
          </div>
        </div>

        <div className="bg-[var(--color-bg-base)] rounded p-3 border border-[var(--color-border)]">
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase mb-1">Unrealized P&L</div>
          <div className="text-sm"><Pnl value={data?.unrealized_pnl ?? 0} /></div>
        </div>
        <div className="bg-[var(--color-bg-base)] rounded p-3 border border-[var(--color-border)]">
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase mb-1">Realized P&L</div>
          <div className="text-sm"><Pnl value={data?.realized_pnl ?? 0} /></div>
        </div>
        <div className="bg-[var(--color-bg-base)] rounded p-3 border border-[var(--color-border)]">
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase mb-1">Free Cash</div>
          <div className="text-sm font-bold text-[color:var(--color-text-primary)]">{fmtUsd(data?.cash ?? 0)}</div>
          {(data?.reserved ?? 0) > 0 && (
            <div className="text-[10px] text-[color:var(--color-text-secondary)] mt-0.5">{fmtUsd(data!.reserved)} reserved</div>
          )}
        </div>
      </div>
    </div>
  );
}
