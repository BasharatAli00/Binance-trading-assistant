'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

interface Holding {
  symbol: string;
  base: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  value: number;
  take_profit: number | null;
  stop_price: number | null;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
}

interface PivotPortfolioData {
  cash: number;
  total_equity: number;
  positions_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  total_pnl_pct: number;
  starting_balance: number;
  holdings: Holding[];
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

export default function PivotPortfolio() {
  const [data, setData] = useState<PivotPortfolioData | null>(null);
  // Recompute-interval customization (strategy #2 only trades on these candles).
  const [interval_, setInterval_] = useState<number | null>(null);
  const [allowed, setAllowed] = useState<number[]>([1, 2, 4, 6, 8, 12]);
  const [selected, setSelected] = useState<number | null>(null);
  const [applying, setApplying] = useState(false);
  const [notice, setNotice] = useState<string>('');

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/pivot-portfolio`);
        const d = await res.json();
        if (!d.error) setData(d);
      } catch (err) {
        console.error("Error fetching pivot portfolio", err);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const fetchInterval = async () => {
      try {
        const res = await fetch(`${API_URL}/api/pivot-interval`);
        const d = await res.json();
        if (!d.error) {
          setInterval_(d.interval_hours);
          setSelected(d.interval_hours);
          if (Array.isArray(d.allowed)) setAllowed(d.allowed);
        }
      } catch (err) {
        console.error("Error fetching pivot interval", err);
      }
    };
    fetchInterval();
  }, []);

  const applyInterval = async () => {
    if (selected == null || selected === interval_) return;
    const ok = window.confirm(
      `Recompute Support/Resistance every ${selected}h?\n\n` +
      `This resets Strategy Two's wallet to $5,000 and clears its trade history ` +
      `so the new interval starts from a clean baseline.`
    );
    if (!ok) return;
    setApplying(true);
    setNotice('');
    try {
      const res = await fetch(`${API_URL}/api/pivot-interval`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interval_hours: selected }),
      });
      const d = await res.json();
      if (d.error) {
        setNotice(d.error);
      } else {
        setInterval_(d.interval_hours);
        setSelected(d.interval_hours);
        setNotice(`Now recomputing every ${d.interval_hours}h · wallet reset`);
      }
    } catch (err) {
      console.error("Error setting pivot interval", err);
      setNotice('Failed to update interval');
    } finally {
      setApplying(false);
    }
  };

  const equity = data?.total_equity ?? 0;
  const totalPnl = data?.total_pnl ?? 0;
  const pnlPct = data?.total_pnl_pct ?? 0;
  const btc = data?.holdings?.find((h) => h.base === 'BTC') ?? null;

  return (
    <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-6 rounded-lg shadow-lg">
      <div className="flex justify-between items-center mb-4">
        <div className="text-[color:var(--color-text-secondary)] text-sm font-medium uppercase">Pivot Bracket (Demo)</div>
        <div className="text-[10px] text-[color:var(--color-text-secondary)] uppercase">Paper · Live Prices</div>
      </div>

      {/* Customize how often Support/Resistance is recomputed */}
      <div className="bg-[var(--color-bg-base)] rounded p-3 border border-[var(--color-border)] mb-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase mb-1">S/R Recompute Interval</div>
            <div className="text-[11px] text-[color:var(--color-text-secondary)]">
              {interval_ != null ? `Currently every ${interval_}h` : 'Loading…'}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={selected ?? ''}
              onChange={(e) => setSelected(Number(e.target.value))}
              disabled={applying || selected == null}
              className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded px-2 py-1 text-sm text-[color:var(--color-text-primary)]"
            >
              {allowed.map((h) => (
                <option key={h} value={h}>{h}h</option>
              ))}
            </select>
            <button
              onClick={applyInterval}
              disabled={applying || selected == null || selected === interval_}
              className="px-3 py-1 rounded text-sm font-bold bg-[#f0b90b] text-black disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {applying ? 'Applying…' : 'Apply'}
            </button>
          </div>
        </div>
        {notice && (
          <div className="text-[10px] text-[color:var(--color-text-secondary)] mt-2">{notice}</div>
        )}
        <div className="text-[10px] text-[color:var(--color-text-secondary)] mt-1">
          Applying resets this wallet to $5,000 for a clean comparison.
        </div>
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
        <div className="bg-[var(--color-bg-base)] rounded p-3 border border-[var(--color-border)]">
          <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase mb-1">Unrealized P&L</div>
          <div className="text-sm"><Pnl value={data?.unrealized_pnl ?? 0} /></div>
        </div>
        <div className="bg-[var(--color-bg-base)] rounded p-3 border border-[var(--color-border)]">
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
              {btc && btc.quantity > 0 && (
                <div className="text-[10px] text-[color:var(--color-text-secondary)]">
                  avg entry {fmtUsd(btc.avg_entry_price)}
                  {btc.take_profit ? ` · TP ${fmtUsd(btc.take_profit)}` : ''}
                  {btc.stop_price ? ` · SL ${fmtUsd(btc.stop_price)}` : ''}
                </div>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[color:var(--color-text-primary)] font-bold">{(btc?.quantity ?? 0).toFixed(6)}</div>
            <div className="text-[10px] text-[color:var(--color-text-secondary)]">{fmtUsd(btc?.value ?? 0)}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
