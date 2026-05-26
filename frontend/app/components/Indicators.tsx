'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

export default function Indicators({ symbol }: { symbol: string }) {
  const [data, setData] = useState<any>(null);
  
  useEffect(() => {
    setData(null);
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/dashboard?symbol=${symbol}`);
        const result = await res.json();
        if (!result.error) setData(result);
      } catch (err) {
        console.error("Error fetching indicators", err);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [symbol]);

  if (!data) return <div className="bg-[#111111] border border-[#222222] p-6 rounded-lg h-full flex items-center justify-center text-gray-500 font-mono">Loading Indicators...</div>;

  const getSignalProps = () => {
    if (data.signal === 'BUY') return { color: 'text-[#00ff88]', bg: 'bg-[#00ff88]/20', border: 'border-[#00ff88]', shadow: 'shadow-[0_0_15px_rgba(0,255,136,0.5)]', icon: '🚀', dot: '🟢' };
    if (data.signal === 'SELL') return { color: 'text-[#ff4466]', bg: 'bg-[#ff4466]/20', border: 'border-[#ff4466]', shadow: 'shadow-[0_0_15px_rgba(255,68,102,0.5)]', icon: '📉', dot: '🔴' };
    return { color: 'text-[#ffbb00]', bg: 'bg-[#ffbb00]/20', border: 'border-[#ffbb00]', shadow: 'shadow-[0_0_15px_rgba(255,187,0,0.5)] animate-pulse', icon: '⏳', dot: '🟡' };
  };
  const sigProps = getSignalProps();

  const rsiPos = Math.min(100, Math.max(0, data.rsi));
  const rsiLeftPos = `${rsiPos}%`;
  
  // Simple width calculation for histogram
  const maxHist = Math.max(50, Math.abs(data.macd_histogram) * 2); 
  const macdWidth = Math.min(50, (Math.abs(data.macd_histogram) / maxHist) * 50);
  
  return (
    <div className="bg-[#111111] border border-[#222222] rounded-lg shadow-lg font-mono flex flex-col hover:border-gray-500 transition-all">
      <div className="p-4 border-b border-[#222222] flex justify-between items-center">
        <span className="text-gray-400 text-sm font-bold font-sans">INDICATORS</span>
        
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1">
            {[...Array(10)].map((_, i) => (
              <div key={i} className={`w-2 h-2 rounded-full ${i < data.signal_strength ? (data.signal_strength <= 3 ? 'bg-[#ff4466]' : data.signal_strength <= 6 ? 'bg-[#ffbb00]' : 'bg-[#00ff88]') : 'bg-gray-700'}`} />
            ))}
            <span className="text-gray-400 text-xs ml-1">{data.signal_strength}/10</span>
          </div>
          <div className={`px-3 py-1 rounded border ${sigProps.bg} ${sigProps.border} ${sigProps.color} ${sigProps.shadow} font-bold flex items-center gap-2`}>
            {sigProps.icon} {data.signal}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 divide-x divide-y divide-[#222222]">
        {/* RSI */}
        <div className="p-4 flex flex-col gap-2">
          <div className="text-gray-400 text-xs">RSI (14)</div>
          
          <div className="relative w-full h-2 bg-gray-800 rounded mt-2">
             <div className="absolute left-0 w-[30%] h-full bg-[#ff4466]/40 rounded-l"></div>
             <div className="absolute left-[30%] w-[40%] h-full bg-white/20"></div>
             <div className="absolute right-[0%] w-[30%] h-full bg-[#ff4466]/40 rounded-r"></div>
             <div className="absolute h-4 w-4 bg-white rounded-full -top-1 -ml-2 shadow shadow-black" style={{ left: rsiLeftPos }}></div>
          </div>
          
          <div className="text-2xl font-bold mt-1 text-white">{data.rsi?.toFixed(2)}</div>
          
          <div className="flex justify-between items-center text-xs">
            {data.rsi_change > 0 ? <span className="text-[#00ff88]">▲ +{data.rsi_change?.toFixed(2)}</span> : <span className="text-[#ff4466]">▼ {data.rsi_change?.toFixed(2)}</span>}
            <span className={`${data.rsi_zone === 'OVERSOLD' || data.rsi_zone === 'OVERBOUGHT' ? 'text-[#ff4466]' : 'text-gray-400'}`}>{data.rsi_zone}</span>
          </div>
        </div>

        {/* MACD */}
        <div className="p-4 flex flex-col gap-2">
          <div className="text-gray-400 text-xs">MACD</div>
          
          <div className="relative w-full h-2 bg-gray-800 mt-2 flex items-center justify-center">
            <div className="absolute w-[2px] h-4 bg-gray-600"></div>
            {data.macd_histogram > 0 ? (
              <div className="absolute h-full bg-[#00ff88]" style={{ width: `${macdWidth}%`, left: '50%' }}></div>
            ) : (
              <div className="absolute h-full bg-[#ff4466]" style={{ width: `${macdWidth}%`, right: '50%' }}></div>
            )}
          </div>
          
          <div className="text-sm mt-1">Hist: {data.macd_histogram > 0 ? <span className="text-[#00ff88]">+{data.macd_histogram?.toFixed(2)}</span> : <span className="text-[#ff4466]">{data.macd_histogram?.toFixed(2)}</span>}</div>
          <div className="text-sm">Trend: {data.macd_trend === 'BULLISH' ? <span className="text-[#00ff88]">🟢 BULLISH</span> : <span className="text-[#ff4466]">🔴 BEARISH</span>}</div>
          <div className="text-xs text-gray-500">Signal: {data.macd?.toFixed(2)}</div>
        </div>

        {/* EMA 20 */}
        <div className="p-4 flex flex-col gap-1">
          <div className="text-gray-400 text-xs">EMA 20</div>
          <div className="text-lg font-bold text-white">${data.ema20?.toLocaleString(undefined, {maximumFractionDigits: 2})}</div>
          <div className="text-sm">
            {data.price_vs_ema20 > 0 ? <span className="text-[#00ff88]">▲ +{data.price_vs_ema20?.toFixed(2)}%</span> : <span className="text-[#ff4466]">▼ {data.price_vs_ema20?.toFixed(2)}%</span>}
          </div>
          <div className="text-xs text-gray-500">{data.price_vs_ema20 > 0 ? 'price above' : 'price below'}</div>
        </div>

        {/* EMA 50 */}
        <div className="p-4 flex flex-col gap-1">
          <div className="text-gray-400 text-xs">EMA 50</div>
          <div className="text-lg font-bold text-white">${data.ema50?.toLocaleString(undefined, {maximumFractionDigits: 2})}</div>
          <div className="text-sm">
            {data.price_vs_ema50 > 0 ? <span className="text-[#00ff88]">▲ +{data.price_vs_ema50?.toFixed(2)}%</span> : <span className="text-[#ff4466]">▼ {data.price_vs_ema50?.toFixed(2)}%</span>}
          </div>
          <div className="text-xs text-gray-500">{data.price_vs_ema50 > 0 ? 'price above' : 'price below'}</div>
        </div>
      </div>
    </div>
  );
}
