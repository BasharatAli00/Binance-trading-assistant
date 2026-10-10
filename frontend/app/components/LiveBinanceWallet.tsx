'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

interface AssetBalance {
  asset: string;
  free: number;
  locked: number;
  total: number;
  usd_value: number;
}

interface LiveWalletData {
  total_usd_value: number;
  balances: AssetBalance[];
  error?: string;
}

const fmtUsd = (n: number) =>
  `$${(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function LiveBinanceWallet() {
  const [data, setData] = useState<LiveWalletData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/live-wallet`);
        const d = await res.json();
        setData(d);
      } catch (err) {
        console.error("Error fetching live wallet", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 10000); // Poll every 10s
    return () => clearInterval(interval);
  }, []);

  if (loading && !data) {
    return (
      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-6 rounded-lg shadow-lg flex items-center justify-center">
        <div className="text-[color:var(--color-text-secondary)]">Loading Live Wallet...</div>
      </div>
    );
  }

  if (data?.error) {
    return (
      <div className="bg-[var(--color-bg-panel)] border border-[#F6465D] p-6 rounded-lg shadow-lg">
        <div className="text-[#F6465D] font-bold text-sm mb-2">Binance Connection Error</div>
        <div className="text-xs text-[color:var(--color-text-secondary)]">{data.error}</div>
      </div>
    );
  }

  const equity = data?.total_usd_value ?? 0;
  const balances = data?.balances || [];

  return (
    <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-6 rounded-lg shadow-lg relative overflow-hidden">
      <div className="absolute top-0 right-0 w-2 h-full bg-[#F3BA2F]"></div>
      
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full flex items-center justify-center bg-[#F3BA2F] text-black font-bold text-xs">
            B
          </div>
          <div className="text-[color:var(--color-text-primary)] text-sm font-bold uppercase tracking-wider">Live Binance Wallet</div>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-[#0ECB81] animate-pulse"></div>
          <div className="text-[10px] text-[#0ECB81] uppercase font-bold tracking-wider">Connected</div>
        </div>
      </div>

      <div className="mb-6">
        <div className="text-[color:var(--color-text-secondary)] text-xs uppercase mb-1">Estimated Total Balance</div>
        <div className="text-3xl font-bold text-[color:var(--color-text-primary)]">{fmtUsd(equity)}</div>
      </div>

      <div className="space-y-3">
        <div className="text-[color:var(--color-text-secondary)] text-[10px] uppercase mb-2 border-b border-[var(--color-border)] pb-2 flex justify-between">
          <span>Asset</span>
          <span>Balance</span>
        </div>
        
        {balances.map((b) => (
          <div key={b.asset} className="flex justify-between items-center">
            <div className="flex items-center gap-2">
              <span className="text-[color:var(--color-text-secondary)] font-bold">{b.asset}</span>
            </div>
            <div className="text-right">
              <div className="text-[color:var(--color-text-primary)] font-bold">{b.total.toLocaleString(undefined, { maximumFractionDigits: 6 })}</div>
              {b.usd_value > 0 && (
                <div className="text-[10px] text-[color:var(--color-text-secondary)]">≈ {fmtUsd(b.usd_value)}</div>
              )}
            </div>
          </div>
        ))}
        {balances.length === 0 && (
          <div className="text-center text-xs text-[color:var(--color-text-secondary)] py-2">
            No assets found in Spot Wallet
          </div>
        )}
      </div>
    </div>
  );
}
