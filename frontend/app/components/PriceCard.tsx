'use client';
import { useEffect, useState } from 'react';

import API_URL from "@/lib/config";

export default function PriceCard({ symbol }: { symbol: string }) {
  const [price, setPrice] = useState<number | null>(null);
  const [prevPrice, setPrevPrice] = useState<number | null>(null);
  
  useEffect(() => {
    // Reset price instantly when symbol changes
    setPrice(null);
    setPrevPrice(null);
    
    const fetchPrice = async () => {
      try {
        const res = await fetch(`${API_URL}/api/price?symbol=${symbol}`);
        const data = await res.json();
        setPrice(prev => {
          setPrevPrice(prev);
          return data.price;
        });
      } catch (err) {
        console.error("Error fetching price", err);
      }
    };
    
    fetchPrice();
    const interval = setInterval(fetchPrice, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  const isUp = price && prevPrice ? price >= prevPrice : true;

  return (
    <div className="bg-[#181a20] border border-[#2b3139] p-6 rounded-lg shadow-lg flex flex-col justify-center items-center">
      <div className="text-gray-400 text-sm mb-2 font-medium uppercase">{symbol.replace('USDT', '/USDT')} Live Price</div>
      <div className={`text-4xl font-bold tracking-tight ${isUp ? 'text-[#0ECB81]' : 'text-[#F6465D]'}`}>
        {price ? `$${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '--'}
      </div>
    </div>
  );
}
