'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

type OnChainData = {
  n_tx: number;
  total_fees_btc: number;
  hash_rate: number;
  difficulty: number;
  estimated_transaction_volume_usd: number;
  volume_7d_avg: number;
  is_volume_spike: boolean;
  is_hash_rate_drop: boolean;
  timestamp: string;
};

export default function OnChainCard() {
  const [data, setData] = useState<OnChainData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/onchain`);
        if (res.ok) {
          const result = await res.json();
          setData(result);
        } else {
          setData(null);
        }
      } catch (err) {
        console.error("Error fetching on-chain stats", err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 300000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg p-4 font-mono shadow-lg flex flex-col min-h-[140px]">
        <div className="text-[color:var(--color-text-secondary)] text-sm font-bold font-sans mb-3">ON-CHAIN (BTC)</div>
        <div className="text-[color:var(--color-text-secondary)] text-sm flex-1 flex items-center justify-center">Loading network stats...</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg p-4 font-mono shadow-lg flex flex-col min-h-[140px]">
        <div className="text-[color:var(--color-text-secondary)] text-sm font-bold font-sans mb-3">ON-CHAIN (BTC)</div>
        <div className="text-[color:var(--color-text-secondary)] text-sm flex-1 flex items-center justify-center">No data available</div>
      </div>
    );
  }

  const formatUsd = (val: number) => {
    if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`;
    if (val >= 1e6) return `$${(val / 1e6).toFixed(1)}M`;
    return `$${val.toLocaleString()}`;
  };
  
  const formatTx = (val: number) => {
    if (val >= 1000) return `${(val / 1000).toFixed(1)}K`;
    return val.toString();
  };

  const activityBadge = data.is_volume_spike 
    ? <span className="text-xs px-2 py-0.5 rounded bg-orange-900 text-orange-300 font-bold">Elevated</span>
    : <span className="text-xs px-2 py-0.5 rounded bg-green-900 text-green-300 font-bold">Normal</span>;

  return (
    <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg p-4 font-mono shadow-lg hover:border-gray-500 transition-colors flex flex-col">
      <div className="flex justify-between items-center mb-4">
        <span className="text-[color:var(--color-text-secondary)] text-sm font-bold font-sans">ON-CHAIN (BTC)</span>
        {activityBadge}
      </div>

      <div className="flex justify-between items-end mb-2">
        <div className="flex flex-col">
          <span className="text-xs text-[color:var(--color-text-secondary)] uppercase tracking-wide">Transactions (24h)</span>
          <span className="text-xl font-bold text-[color:var(--color-text-primary)]">{formatTx(data.n_tx)}</span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-xs text-[color:var(--color-text-secondary)] uppercase tracking-wide">Est. Volume</span>
          <span className="text-xl font-bold text-[color:var(--color-text-primary)]">{formatUsd(data.estimated_transaction_volume_usd)}</span>
        </div>
      </div>
      
      {data.is_hash_rate_drop && (
        <div className="mt-2 text-xs text-red-400 bg-red-900/30 px-2 py-1 rounded border border-red-900">
          ⚠️ Warning: Significant Hash Rate Drop Detected
        </div>
      )}
    </div>
  );
}
