'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

export default function PriceChangeTimeline({ symbol }: { symbol: string }) {
  const [data, setData] = useState<any>(null);
  
  useEffect(() => {
    setData(null);
    const fetchDashboard = async () => {
      try {
        const res = await fetch(`${API_URL}/api/dashboard?symbol=${symbol}`);
        const result = await res.json();
        if (!result.error) setData(result);
      } catch (err) {
        console.error("Error fetching timeline", err);
      }
    };
    
    fetchDashboard();
    const interval = setInterval(fetchDashboard, 60000); // 60s
    return () => clearInterval(interval);
  }, [symbol]);

  if (!data || !data.timeline) return <div className="h-24 bg-[#111111] border border-[#222222] rounded-lg animate-pulse"></div>;

  // Find max absolute value to scale bars
  const maxAbs = Math.max(...data.timeline.map((v: number) => Math.abs(v)), 0.1);

  return (
    <div className="bg-[#111111] border border-[#222222] p-4 rounded-lg flex flex-col justify-center h-full hover:border-gray-500 transition-colors shadow-lg">
      <div className="flex justify-between items-center mb-3">
         <span className="text-gray-400 text-xs font-bold font-sans">24H TIMELINE (1H BARS)</span>
      </div>
      <div className="flex items-end gap-1 h-12 w-full">
        {data.timeline.map((val: number, i: number) => {
          const heightPct = (Math.abs(val) / maxAbs) * 100;
          return (
            <div 
              key={i} 
              title={`${val > 0 ? '+' : ''}${val.toFixed(2)}%`}
              className={`flex-1 rounded-t-sm ${val >= 0 ? 'bg-[#00ff88]' : 'bg-[#ff4466]'}`} 
              style={{ height: `${Math.max(10, heightPct)}%` }}
            ></div>
          )
        })}
      </div>
    </div>
  );
}
