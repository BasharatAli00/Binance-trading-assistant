'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

export default function LiquidityPortfolio() {
  const [data, setData] = useState<any>(null);
  const [stateData, setStateData] = useState<any>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [portRes, stateRes] = await Promise.all([
          fetch(`${API_URL}/api/liquidity-portfolio`),
          fetch(`${API_URL}/api/liquidity-state`)
        ]);
        const port = await portRes.json();
        const st = await stateRes.json();
        setData(port);
        setStateData(st);
      } catch (err) {
        console.error(err);
      }
    };
    fetchData();
    const iv = setInterval(fetchData, 1000);
    return () => clearInterval(iv);
  }, []);

  if (!data) return <div className="card text-[var(--color-text-secondary)]">Loading Liquidity Scalper...</div>;

  return (
    <div className="card flex flex-col gap-4">
      <div className="flex justify-between items-center border-b border-[var(--color-border)] pb-2 mb-2">
        <h3 className="text-xl font-bold text-[color:var(--color-text-primary)]">Liquidity Scalper (1m/5m)</h3>
        <div className={`px-2 py-1 rounded text-xs font-bold ${
            stateData?.status === 'IN_POSITION' ? 'bg-[var(--color-win)] text-white' : 
            stateData?.status === 'ARMED' ? 'bg-orange-500 text-white' : 
            stateData?.status === 'SWEPT' ? 'bg-yellow-500 text-black' : 
            'bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)]'}`}>
            {stateData?.status || 'OFFLINE'}
        </div>
      </div>
      
      <div className="flex flex-col gap-1 text-sm bg-[var(--color-bg-hover)] p-3 rounded">
        <div className="text-[var(--color-text-secondary)]">Engine Status</div>
        <div className="font-mono text-xs">{stateData?.message}</div>
        {stateData?.sweep_level && (
            <div className="mt-1 font-mono text-xs text-[var(--color-win)]">Swept Pool: ${stateData.sweep_level}</div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-sm text-[var(--color-text-secondary)] font-medium mb-1">Total Equity</div>
          <div className="text-2xl font-black font-mono tracking-tight text-[color:var(--color-text-primary)]">
            ${data.total_equity?.toFixed(2)}
          </div>
          <div className={`text-sm font-bold ${data.total_pnl >= 0 ? 'text-[var(--color-win)]' : 'text-[var(--color-loss)]'}`}>
            {data.total_pnl >= 0 ? '+' : ''}{data.total_pnl?.toFixed(2)} ({data.total_pnl_pct?.toFixed(2)}%)
          </div>
        </div>
        <div>
          <div className="text-sm text-[var(--color-text-secondary)] font-medium mb-1">Cash (USDT)</div>
          <div className="text-2xl font-black font-mono tracking-tight text-[color:var(--color-text-primary)]">
            ${data.cash?.toFixed(2)}
          </div>
        </div>
      </div>

      {data.holdings && data.holdings.length > 0 && (
        <div className="mt-4 pt-4 border-t border-[var(--color-border)]">
          <div className="text-sm text-[var(--color-text-secondary)] font-medium mb-2">Open Positions</div>
          {data.holdings.map((h: any) => (
            <div key={h.symbol} className="flex justify-between items-center bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-2 rounded">
              <div>
                <span className="font-bold text-[color:var(--color-text-primary)]">{h.symbol}</span>
                <span className="ml-2 text-xs text-[var(--color-text-secondary)]">{h.quantity.toFixed(4)} qty</span>
              </div>
              <div className="text-right">
                <div className={`font-mono text-sm font-bold ${h.unrealized_pnl >= 0 ? 'text-[var(--color-win)]' : 'text-[var(--color-loss)]'}`}>
                  ${h.unrealized_pnl.toFixed(2)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
