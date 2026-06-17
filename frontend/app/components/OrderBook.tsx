'use client';
import { useEffect, useState } from 'react';
import API_URL from "@/lib/config";

type Level = { price: number; qty: number };
type BookData = { symbol: string; bids: Level[]; asks: Level[]; fetched_at: number };

export default function OrderBook({ symbol }: { symbol: string }) {
  const [data, setData] = useState<BookData | null>(null);

  useEffect(() => {
    setData(null);
    const fetchBook = async () => {
      try {
        const res = await fetch(`${API_URL}/api/orderbook?symbol=${symbol}`);
        const result = await res.json();
        if (!result.error) setData(result);
      } catch (err) {
        console.error("Error fetching order book", err);
      }
    };
    fetchBook();
    const interval = setInterval(fetchBook, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  if (!data || (!data.bids?.length && !data.asks?.length)) {
    return (
      <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg">
        <div className="text-gray-400 text-sm font-bold font-sans mb-2">ORDER BOOK</div>
        <div className="text-gray-500 text-sm">Loading depth…</div>
      </div>
    );
  }

  // Top 3 of each side; asks shown best (lowest) first, descending visually.
  const asks = data.asks.slice(0, 3);
  const bids = data.bids.slice(0, 3);
  const fmtP = (n: number) => n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtQ = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 4 });

  const spread = asks.length && bids.length ? asks[0].price - bids[0].price : 0;

  return (
    <div className="bg-[#111111] border border-[#222222] rounded-lg p-4 font-mono shadow-lg hover:border-gray-500 transition-colors">
      <div className="flex justify-between items-center mb-3">
        <span className="text-gray-400 text-sm font-bold font-sans">ORDER BOOK</span>
        <span className="text-xs text-gray-500">Top 3 · spread ${fmtP(spread)}</span>
      </div>

      <div className="grid grid-cols-2 text-[10px] text-gray-600 mb-1">
        <span>PRICE</span>
        <span className="text-right">AMOUNT</span>
      </div>

      {/* Asks (sell side) — red, best ask at the bottom near the spread */}
      <div className="space-y-1">
        {[...asks].reverse().map((a, i) => (
          <div key={`a${i}`} className="grid grid-cols-2 text-sm">
            <span className="text-[#ff4466]">{fmtP(a.price)}</span>
            <span className="text-right text-gray-300">{fmtQ(a.qty)}</span>
          </div>
        ))}
      </div>

      <div className="my-2 border-t border-[#222222]" />

      {/* Bids (buy side) — green, best bid at the top near the spread */}
      <div className="space-y-1">
        {bids.map((b, i) => (
          <div key={`b${i}`} className="grid grid-cols-2 text-sm">
            <span className="text-[#00ff88]">{fmtP(b.price)}</span>
            <span className="text-right text-gray-300">{fmtQ(b.qty)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
