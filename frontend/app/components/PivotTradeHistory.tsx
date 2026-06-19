'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

interface Trade {
  timestamp: string;
  symbol: string;
  side: string;
  price: number;
  quantity: number;
  quote_amount: number;
  fee: number;
  realized_pnl: number;
  reason: string;
}

export default function PivotTradeHistory({ symbol }: { symbol: string }) {
  const [trades, setTrades] = useState<Trade[]>([]);

  useEffect(() => {
    const fetchTrades = async () => {
      try {
        const res = await fetch(`${API_URL}/api/pivot-trades?symbol=${symbol}`);
        const data = await res.json();
        if (Array.isArray(data)) {
          setTrades(data);
        }
      } catch (err) {
        console.error("Error fetching pivot trades", err);
      }
    };
    fetchTrades();
    const interval = setInterval(fetchTrades, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  return (
    <div className="bg-[#181a20] border border-[#2b3139] p-6 rounded-lg shadow-lg flex-grow overflow-hidden flex flex-col min-h-[300px]">
      <div className="text-gray-400 text-sm font-medium uppercase mb-4">
        {symbol.replace('USDT', '')} Pivot-Bracket Trade History
      </div>

      <div className="overflow-x-auto flex-grow">
        <table className="w-full text-left text-sm">
          <thead className="text-gray-500 uppercase text-xs border-b border-[#2b3139]">
            <tr>
              <th className="pb-3 font-medium">Time</th>
              <th className="pb-3 font-medium">Type</th>
              <th className="pb-3 font-medium">Price</th>
              <th className="pb-3 font-medium text-right">Amount</th>
              <th className="pb-3 font-medium text-right">P&L</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#2b3139]/50">
            {trades.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-8 text-center text-gray-500">No pivot trades yet for {symbol}</td>
              </tr>
            ) : (
              trades.map((trade, i) => (
                <tr key={i} className="hover:bg-[#2b3139]/20 transition-colors" title={trade.reason}>
                  <td className="py-3 text-gray-300">{(trade.timestamp || '').split(' ')[1]}</td>
                  <td className={`py-3 font-bold ${trade.side === 'BUY' ? 'text-[#0ECB81]' : 'text-[#F6465D]'}`}>
                    {trade.side}
                  </td>
                  <td className="py-3 text-gray-200">${(trade.price || 0).toFixed(2)}</td>
                  <td className="py-3 text-gray-200 text-right">{(trade.quantity || 0).toFixed(6)}</td>
                  <td className="py-3 text-right">
                    {trade.side === 'SELL' ? (
                      <span className={`font-bold ${(trade.realized_pnl || 0) >= 0 ? 'text-[#0ECB81]' : 'text-[#F6465D]'}`}>
                        {(trade.realized_pnl || 0) >= 0 ? '+' : ''}${(trade.realized_pnl || 0).toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
