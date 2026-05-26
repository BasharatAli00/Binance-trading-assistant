'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

export default function MarketStatsRow({ symbol }: { symbol: string }) {
  const [data, setData] = useState<any>(null);
  
  useEffect(() => {
    setData(null);
    const fetchDashboard = async () => {
      try {
        const res = await fetch(`${API_URL}/api/dashboard?symbol=${symbol}`);
        const result = await res.json();
        if (!result.error) setData(result);
      } catch (err) {
        console.error("Error fetching market stats", err);
      }
    };
    
    fetchDashboard();
    const interval = setInterval(fetchDashboard, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  if (!data) return <div className="h-24 bg-[#111111] border border-[#222222] rounded-lg animate-pulse"></div>;

  return (
    <div className="bg-[#111111] border border-[#222222] rounded-lg grid grid-cols-2 md:grid-cols-5 divide-x divide-y md:divide-y-0 divide-[#222222] font-mono shadow-lg hover:border-gray-500 transition-colors">
      <div className="p-4 flex flex-col gap-1">
        <div className="text-gray-400 text-xs font-sans font-bold">24H HIGH</div>
        <div className="text-lg text-white">${data.high_24h?.toLocaleString(undefined, {maximumFractionDigits: 2})}</div>
        <div className="text-xs text-gray-500">24h Resistance</div>
      </div>
      <div className="p-4 flex flex-col gap-1">
        <div className="text-gray-400 text-xs font-sans font-bold">24H LOW</div>
        <div className="text-lg text-white">${data.low_24h?.toLocaleString(undefined, {maximumFractionDigits: 2})}</div>
        <div className="text-xs text-gray-500">24h Support</div>
      </div>
      <div className="p-4 flex flex-col gap-1">
        <div className="text-gray-400 text-xs font-sans font-bold">VOLUME 24H</div>
        <div className="text-lg text-white">${(data.volume_24h)?.toLocaleString(undefined, {maximumFractionDigits: 2})}</div>
        <div className="text-xs text-gray-500">Base asset volume</div>
      </div>
      <div className="p-4 flex flex-col gap-1">
        <div className="text-gray-400 text-xs font-sans font-bold">VOLATILITY</div>
        <div className="text-lg text-white">{data.volatility?.toFixed(2)}%</div>
        <div className="text-xs text-gray-500">{data.volatility > 2 ? 'HIGH' : 'LOW'}</div>
      </div>
      <div className="p-4 flex flex-col gap-1">
        <div className="text-gray-400 text-xs font-sans font-bold">TRADES</div>
        <div className="text-lg text-white">{data.trade_count_24h?.toLocaleString()}</div>
        <div className="text-xs text-gray-500">Total in 24h</div>
      </div>
    </div>
  );
}
