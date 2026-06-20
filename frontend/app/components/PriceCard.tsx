'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

export default function PriceCard({ symbol }: { symbol: string }) {
  const [data, setData] = useState<any>(null);
  const [flash, setFlash] = useState<'up' | 'down' | null>(null);
  
  useEffect(() => {
    setData(null);
    const fetchDashboard = async () => {
      try {
        const res = await fetch(`${API_URL}/api/dashboard?symbol=${symbol}`);
        const result = await res.json();
        
        if (!result.error) {
          setData((prev: any) => {
            if (prev && prev.price && result.price !== prev.price) {
              setFlash(result.price > prev.price ? 'up' : 'down');
              setTimeout(() => setFlash(null), 1000);
            }
            return result;
          });
        }
      } catch (err) {
        console.error("Error fetching dashboard", err);
      }
    };
    
    fetchDashboard();
    const interval = setInterval(fetchDashboard, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  if (!data) return <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-6 rounded-lg h-full flex items-center justify-center text-[color:var(--color-text-secondary)] font-mono">Loading...</div>;

  const PriceArrow = ({ val }: { val: number }) => {
    if (val > 0) return <span className="text-[#00ff88]">▲ +{val.toFixed(2)}%</span>;
    if (val < 0) return <span className="text-[#ff4466]">▼ {val.toFixed(2)}%</span>;
    return <span className="text-[color:var(--color-text-secondary)]">— 0.00%</span>;
  };

  return (
    <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] p-6 rounded-lg shadow-lg hover:border-gray-500 transition-all font-mono flex flex-col gap-4">
      <div className="text-[color:var(--color-text-secondary)] text-sm font-sans font-bold">{symbol.replace('USDT', '/USDT')}</div>
      
      <div className="flex justify-between items-end">
        <div className={`text-4xl font-bold tracking-tight transition-colors duration-300 ${flash === 'up' ? 'text-[#00ff88]' : flash === 'down' ? 'text-[#ff4466]' : 'text-[color:var(--color-text-primary)]'}`}>
          ${data.price?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
        <div className="text-lg">
          <PriceArrow val={data.price_change_24h} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm mt-2">
        <div>1H <PriceArrow val={data.price_change_1h} /></div>
        <div>4H <PriceArrow val={data.price_change_4h} /></div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        <div>24H <PriceArrow val={data.price_change_24h} /></div>
        <div>Vol {data.volume_change_24h > 0 ? <span className="text-[#00ff88]">▲ +{data.volume_change_24h?.toFixed(2)}%</span> : <span className="text-[#ff4466]">▼ {data.volume_change_24h?.toFixed(2)}%</span>}</div>
      </div>

      <div className="mt-4 pt-4 border-t border-[var(--color-border)] text-xs text-[color:var(--color-text-secondary)] space-y-1">
        <div className="flex justify-between">
          <span>H: ${data.high_24h?.toLocaleString(undefined, {maximumFractionDigits: 2})}</span>
          <span>L: ${data.low_24h?.toLocaleString(undefined, {maximumFractionDigits: 2})}</span>
        </div>
        <div className="flex justify-between">
          <span>VWAP: ${data.weighted_avg_price?.toLocaleString(undefined, {maximumFractionDigits: 2})}</span>
          <span>Trades: {data.trade_count_24h?.toLocaleString()}</span>
        </div>
      </div>
    </div>
  );
}
