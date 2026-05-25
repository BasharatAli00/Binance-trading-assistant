'use client';
import { useEffect, useState } from 'react';

import API_URL from "@/lib/config";

interface Trade {
  Timestamp: string;
  Symbol: string;
  Signal: string;
  Price: string;
  Amount: string;
  'Order ID': string;
}

export default function TradeHistory({ symbol }: { symbol: string }) {
  const [trades, setTrades] = useState<Trade[]>([]);

  useEffect(() => {
    const fetchTrades = async () => {
      try {
        const res = await fetch(`${API_URL}/api/trades?symbol=${symbol}`);
        const data = await res.json();
        if (Array.isArray(data)) {
          setTrades(data);
        }
      } catch (err) {
        console.error("Error fetching trades", err);
      }
    };
    
    fetchTrades();
    const interval = setInterval(fetchTrades, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  return (
    <div className="bg-[#181a20] border border-[#2b3139] p-6 rounded-lg shadow-lg flex-grow overflow-hidden flex flex-col min-h-[300px]">
      <div className="text-gray-400 text-sm font-medium uppercase mb-4">{symbol.replace('USDT', '')} Trade History</div>
      
      <div className="overflow-x-auto flex-grow">
        <table className="w-full text-left text-sm">
          <thead className="text-gray-500 uppercase text-xs border-b border-[#2b3139]">
            <tr>
              <th className="pb-3 font-medium">Time</th>
              <th className="pb-3 font-medium">Type</th>
              <th className="pb-3 font-medium">Price</th>
              <th className="pb-3 font-medium text-right">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#2b3139]/50">
            {trades.length === 0 ? (
              <tr>
                <td colSpan={4} className="py-8 text-center text-gray-500">No trades yet for {symbol}</td>
              </tr>
            ) : (
              trades.map((trade, i) => (
                <tr key={i} className="hover:bg-[#2b3139]/20 transition-colors">
                  <td className="py-3 text-gray-300">{trade.Timestamp.split(' ')[1]}</td>
                  <td className={`py-3 font-bold ${trade.Signal === 'BUY' ? 'text-[#0ECB81]' : 'text-[#F6465D]'}`}>
                    {trade.Signal}
                  </td>
                  <td className="py-3 text-gray-200">${parseFloat(trade.Price).toFixed(2)}</td>
                  <td className="py-3 text-gray-200 text-right">{parseFloat(trade.Amount).toFixed(4)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
