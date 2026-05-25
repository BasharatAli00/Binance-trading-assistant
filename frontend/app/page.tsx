'use client';
import { useState, useEffect } from 'react';
import PriceCard from './components/PriceCard';
import CandleChart from './components/CandleChart';
import Indicators from './components/Indicators';
import Portfolio from './components/Portfolio';
import TradeHistory from './components/TradeHistory';
import BotSettings from './components/BotSettings';

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const COIN_COLORS: Record<string, string> = {
  'BTCUSDT': '#F7931A',
  'ETHUSDT': '#627EEA',
  'SOLUSDT': '#9945FF',
  'BNBUSDT': '#F3BA2F'
};

export default function Home() {
  const [selectedCoin, setSelectedCoin] = useState('BTCUSDT');
  const [coinsOverview, setCoinsOverview] = useState<any[]>([]);

  useEffect(() => {
    const fetchOverview = async () => {
      try {
        const res = await fetch(`${API_URL}/api/allcoins`);
        const data = await res.json();
        setCoinsOverview(data);
      } catch (err) {
        console.error(err);
      }
    };
    fetchOverview();
    const interval = setInterval(fetchOverview, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <main className="min-h-screen lg:h-screen lg:overflow-hidden bg-[#0f0f0f] text-gray-200 font-sans p-6">
      <div className="max-w-[1600px] mx-auto h-full flex flex-col space-y-4">
        
        {/* Header */}
        <header className="shrink-0 flex justify-between items-center pb-2 border-b border-[#2b3139]">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-[#FCD535] rounded-lg flex items-center justify-center">
              <svg className="w-6 h-6 text-black" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            </div>
            <div>
              <h1 className="text-xl font-bold text-white tracking-wide">Binance Trader Pro</h1>
              <div className="text-[#0ECB81] text-xs font-medium flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-[#0ECB81]"></span>
                System Online
              </div>
            </div>
          </div>
          
          {/* Coin Selector Tabs */}
          <div className="flex gap-2 bg-[#181a20] p-1 rounded-lg border border-[#2b3139]">
            {['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'].map(sym => (
              <button 
                key={sym}
                onClick={() => setSelectedCoin(sym)}
                className={`px-4 py-2 rounded-md font-bold transition-colors ${selectedCoin === sym ? 'bg-[#2b3139] text-white' : 'text-gray-400 hover:text-gray-200'}`}
                style={{ color: selectedCoin === sym ? COIN_COLORS[sym] : undefined }}
              >
                {sym.replace('USDT', '')}
              </button>
            ))}
          </div>
        </header>

        {/* Coin Overview Bar */}
        <div className="shrink-0 grid grid-cols-2 lg:grid-cols-4 gap-4">
          {coinsOverview.length > 0 ? coinsOverview.map(coin => (
            <div 
              key={coin.symbol} 
              onClick={() => setSelectedCoin(coin.symbol)}
              className={`bg-[#181a20] border cursor-pointer p-4 rounded-lg flex flex-col transition-colors ${selectedCoin === coin.symbol ? '' : 'border-[#2b3139] hover:border-gray-500'}`}
              style={{ borderColor: selectedCoin === coin.symbol ? COIN_COLORS[coin.symbol] : undefined }}
            >
              <div className="text-gray-400 text-sm font-bold mb-1 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: COIN_COLORS[coin.symbol] }}></span>
                {coin.symbol.replace('USDT', '/USDT')}
              </div>
              <div className="text-xl font-bold text-white">${coin.price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
              <div className="flex justify-between items-center mt-2 text-xs">
                <span className="text-gray-400">RSI: {coin.rsi.toFixed(2)}</span>
                <span className={`px-2 py-1 rounded font-bold ${coin.signal === 'BUY' ? 'bg-[#0ECB81]/20 text-[#0ECB81]' : coin.signal === 'SELL' ? 'bg-[#F6465D]/20 text-[#F6465D]' : 'bg-[#FCD535]/20 text-[#FCD535]'}`}>
                  {coin.signal}
                </span>
              </div>
            </div>
          )) : (
            <div className="col-span-4 text-center text-gray-500 text-sm py-4">Loading coin data...</div>
          )}
        </div>

        {/* Main Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 flex-grow lg:overflow-hidden pb-4">
          
          {/* Left Column */}
          <div className="flex flex-col gap-6 lg:overflow-y-auto custom-scrollbar pr-2 pb-2">
            <PriceCard symbol={selectedCoin} />
            <Portfolio />
            <BotSettings />
          </div>

          {/* Center Column (Chart) */}
          <div className="lg:col-span-2 flex flex-col min-h-[400px]">
            <CandleChart symbol={selectedCoin} />
          </div>

          {/* Right Column */}
          <div className="flex flex-col gap-6 lg:overflow-y-auto custom-scrollbar pr-2 pb-2">
            <Indicators symbol={selectedCoin} />
            <TradeHistory symbol={selectedCoin} />
          </div>

        </div>
      </div>
    </main>
  );
}
