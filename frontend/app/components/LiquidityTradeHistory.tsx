'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

export default function LiquidityTradeHistory({ symbol }: { symbol: string }) {
  const [trades, setTrades] = useState<any[]>([]);

  useEffect(() => {
    const fetchTrades = async () => {
      try {
        const res = await fetch(`${API_URL}/api/liquidity-trades`);
        const data = await res.json();
        setTrades(data);
      } catch (err) {
        console.error(err);
      }
    };
    fetchTrades();
    const iv = setInterval(fetchTrades, 2000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="card h-full flex flex-col">
      <h3 className="text-xl font-bold text-[color:var(--color-text-primary)] mb-4">Scalper Log</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="text-[10px] text-[var(--color-text-secondary)] uppercase bg-[var(--color-bg-hover)] border-b border-[var(--color-border)]">
            <tr>
              <th className="py-2 px-3">Time</th>
              <th className="py-2 px-3">Side</th>
              <th className="py-2 px-3">Price</th>
              <th className="py-2 px-3">Qty</th>
              <th className="py-2 px-3">PnL</th>
              <th className="py-2 px-3">Reason</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t: any, i: number) => (
              <tr key={i} className="border-b border-[var(--color-border)] hover:bg-[var(--color-bg-hover)] transition-colors">
                <td className="py-2 px-3 font-mono text-xs text-[var(--color-text-secondary)]">{t.timestamp}</td>
                <td className={`py-2 px-3 font-bold ${t.side === 'BUY' ? 'text-[var(--color-win)]' : 'text-[var(--color-loss)]'}`}>
                  {t.side}
                </td>
                <td className="py-2 px-3 font-mono text-[color:var(--color-text-primary)]">${t.price?.toFixed(2)}</td>
                <td className="py-2 px-3 font-mono text-[color:var(--color-text-primary)]">{t.quantity?.toFixed(4)}</td>
                <td className={`py-2 px-3 font-mono font-bold ${t.realized_pnl > 0 ? 'text-[var(--color-win)]' : t.realized_pnl < 0 ? 'text-[var(--color-loss)]' : 'text-[var(--color-text-secondary)]'}`}>
                  {t.realized_pnl !== 0 ? (t.realized_pnl > 0 ? '+' : '') + t.realized_pnl.toFixed(2) : '-'}
                </td>
                <td className="py-2 px-3 text-xs text-[var(--color-text-secondary)]">{t.reason}</td>
              </tr>
            ))}
            {trades.length === 0 && (
              <tr>
                <td colSpan={6} className="py-4 text-center text-[var(--color-text-secondary)]">No trades yet</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
