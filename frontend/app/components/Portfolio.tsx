'use client';
import { useEffect, useState } from 'react';

const COIN_COLORS: Record<string, string> = {
  'USDT': '#0ECB81',
  'BTC': '#F7931A',
  'ETH': '#627EEA',
  'SOL': '#9945FF',
  'BNB': '#F3BA2F'
};

export default function Portfolio() {
  const [balance, setBalance] = useState<Record<string, number>>({ USDT: 0, BTC: 0, ETH: 0, SOL: 0, BNB: 0 });
  const [prices, setPrices] = useState<Record<string, number>>({});

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [balRes, coinsRes] = await Promise.all([
          fetch('http://localhost:8000/api/balance'),
          fetch('http://localhost:8000/api/allcoins')
        ]);
        const balData = await balRes.json();
        const coinsData = await coinsRes.json();
        
        setBalance(balData || {});
        
        const newPrices: Record<string, number> = {};
        if (Array.isArray(coinsData)) {
            coinsData.forEach(c => {
                newPrices[c.symbol.replace('USDT', '')] = c.price;
            });
        }
        setPrices(newPrices);
      } catch (err) {
        console.error("Error fetching portfolio data", err);
      }
    };
    
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const totalUsd = (balance.USDT || 0) + 
    (balance.BTC || 0) * (prices.BTC || 0) +
    (balance.ETH || 0) * (prices.ETH || 0) +
    (balance.SOL || 0) * (prices.SOL || 0) +
    (balance.BNB || 0) * (prices.BNB || 0);

  const renderCoinRow = (sym: string, amount: number) => {
    if (amount <= 0 && sym !== 'USDT') return null; // Only show non-zero balances, always show USDT
    
    const color = COIN_COLORS[sym] || '#FFF';
    
    return (
      <div key={sym} className="flex justify-between items-center pb-2 border-b border-[#2b3139] last:border-0 last:pb-0">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full flex items-center justify-center font-bold text-xs" style={{ backgroundColor: color + '33', color: color }}>
            {sym[0]}
          </div>
          <span className="text-gray-300 font-medium">{sym}</span>
        </div>
        <span className="text-white font-bold">{sym === 'USDT' ? `$${amount.toFixed(2)}` : amount.toFixed(5)}</span>
      </div>
    );
  };

  return (
    <div className="bg-[#181a20] border border-[#2b3139] p-6 rounded-lg shadow-lg">
      <div className="text-gray-400 text-sm font-medium uppercase mb-4">Portfolio</div>
      
      <div className="mb-6">
        <div className="text-gray-500 text-xs uppercase mb-1">Total Estimated Value</div>
        <div className="text-3xl font-bold text-white">
          ${totalUsd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
      </div>
      
      <div className="space-y-3">
        {['USDT', 'BTC', 'ETH', 'SOL', 'BNB'].map(sym => renderCoinRow(sym, balance[sym] || 0))}
      </div>
    </div>
  );
}
