'use client';
import { useState, useEffect } from 'react';
import { Star, TrendingUp, TrendingDown, MoreHorizontal, Bell } from 'lucide-react';

const INITIAL_WATCHLIST = [
  { symbol: 'BTC', name: 'Bitcoin', price: 64230.50, change24h: 2.4, volume: '32.5B', marketCap: '1.2T' },
  { symbol: 'ETH', name: 'Ethereum', price: 3450.20, change24h: 1.8, volume: '15.2B', marketCap: '415B' },
  { symbol: 'BNB', name: 'Binance Coin', price: 590.10, change24h: -0.5, volume: '1.8B', marketCap: '91B' },
  { symbol: 'SOL', name: 'Solana', price: 145.80, change24h: 5.2, volume: '4.1B', marketCap: '65B' },
  { symbol: 'XRP', name: 'Ripple', price: 0.58, change24h: -1.2, volume: '1.1B', marketCap: '32B' },
  { symbol: 'ADA', name: 'Cardano', price: 0.45, change24h: 0.3, volume: '450M', marketCap: '16B' },
  { symbol: 'DOGE', name: 'Dogecoin', price: 0.16, change24h: 8.4, volume: '2.3B', marketCap: '23B' },
];

export default function WatchlistPage() {
  const [watchlist, setWatchlist] = useState(INITIAL_WATCHLIST);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newCoinSymbol, setNewCoinSymbol] = useState('');

  const handleAddCoin = (e: React.FormEvent) => {
    e.preventDefault();
    if (newCoinSymbol.trim()) {
      const symbol = newCoinSymbol.toUpperCase();
      if (!watchlist.find(c => c.symbol === symbol)) {
        setWatchlist(prev => [{
          symbol,
          name: symbol + ' Token',
          price: 10 + Math.random() * 90,
          change24h: (Math.random() - 0.5) * 10,
          volume: Math.floor(100 + Math.random() * 900) + 'M',
          marketCap: Math.floor(1 + Math.random() * 50) + 'B'
        }, ...prev]);
      }
      setNewCoinSymbol('');
      setIsAddModalOpen(false);
    }
  };

  // Simulate real-time price updates
  useEffect(() => {
    const interval = setInterval(() => {
      setWatchlist(prev => prev.map(coin => {
        const volatility = coin.price * 0.001; // 0.1% volatility
        const change = (Math.random() - 0.5) * volatility;
        return {
          ...coin,
          price: coin.price + change
        };
      }));
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex flex-col gap-6 max-w-7xl mx-auto w-full">
      <header className="shrink-0 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-3 border-b border-[var(--color-border)]">
        <div className="flex items-center gap-3">
          <Star className="w-8 h-8 text-[var(--color-brand)] fill-[var(--color-brand)]" />
          <h2 className="text-2xl font-bold text-[color:var(--color-text-primary)] tracking-wide">My Watchlist</h2>
        </div>
        <div className="flex gap-3">
          <button 
            onClick={() => setIsAddModalOpen(true)}
            className="px-4 py-2 bg-[var(--color-bg-hover)] text-[var(--color-text-primary)] rounded-lg font-medium hover:bg-[var(--color-border)] transition-colors text-sm border border-[var(--color-border)]"
          >
            + Add Coin
          </button>
        </div>
      </header>

      <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-xl shadow-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[var(--color-bg-base)] border-b border-[var(--color-border)]">
                <th className="p-4 text-[color:var(--color-text-secondary)] font-medium text-sm">Asset</th>
                <th className="p-4 text-[color:var(--color-text-secondary)] font-medium text-sm text-right">Price</th>
                <th className="p-4 text-[color:var(--color-text-secondary)] font-medium text-sm text-right">24h Change</th>
                <th className="p-4 text-[color:var(--color-text-secondary)] font-medium text-sm text-right hidden sm:table-cell">24h Volume</th>
                <th className="p-4 text-[color:var(--color-text-secondary)] font-medium text-sm text-right hidden md:table-cell">Market Cap</th>
                <th className="p-4 text-[color:var(--color-text-secondary)] font-medium text-sm text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {watchlist.map((coin) => (
                <tr key={coin.symbol} className="hover:bg-[var(--color-bg-hover)] transition-colors group cursor-pointer">
                  <td className="p-4">
                    <div className="flex items-center gap-3">
                      <Star className="w-4 h-4 text-[var(--color-brand)] fill-[var(--color-brand)] shrink-0" />
                      <div className="w-8 h-8 rounded-full bg-[var(--color-bg-base)] flex items-center justify-center font-bold text-xs text-[color:var(--color-text-primary)] shrink-0">
                        {coin.symbol[0]}
                      </div>
                      <div>
                        <div className="font-bold text-[color:var(--color-text-primary)]">{coin.symbol}</div>
                        <div className="text-xs text-[color:var(--color-text-secondary)]">{coin.name}</div>
                      </div>
                    </div>
                  </td>
                  <td className="p-4 text-right font-mono font-medium text-[color:var(--color-text-primary)]">
                    ${coin.price < 1 ? coin.price.toFixed(4) : coin.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </td>
                  <td className="p-4 text-right">
                    <div className={`flex items-center justify-end gap-1 font-medium ${coin.change24h >= 0 ? 'text-[#00ff88]' : 'text-[#ff4466]'}`}>
                      {coin.change24h >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                      {Math.abs(coin.change24h)}%
                    </div>
                  </td>
                  <td className="p-4 text-right text-[color:var(--color-text-secondary)] hidden sm:table-cell">
                    ${coin.volume}
                  </td>
                  <td className="p-4 text-right text-[color:var(--color-text-secondary)] hidden md:table-cell">
                    ${coin.marketCap}
                  </td>
                  <td className="p-4 text-right">
                    <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button className="p-2 hover:bg-[var(--color-bg-base)] rounded-lg text-[var(--color-text-secondary)] transition-colors" title="Set Alert">
                        <Bell className="w-4 h-4" />
                      </button>
                      <button className="p-2 hover:bg-[var(--color-bg-base)] rounded-lg text-[var(--color-text-secondary)] transition-colors" title="More Actions">
                        <MoreHorizontal className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Coin Modal */}
      {isAddModalOpen && (
        <div className="fixed inset-0 bg-black/60 z-[100] flex items-center justify-center p-4">
          <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-xl shadow-2xl w-full max-w-md overflow-hidden">
            <div className="p-4 border-b border-[var(--color-border)] flex justify-between items-center">
              <h3 className="font-bold text-lg text-[color:var(--color-text-primary)]">Add to Watchlist</h3>
              <button 
                onClick={() => setIsAddModalOpen(false)}
                className="text-[var(--color-text-secondary)] hover:text-[color:var(--color-text-primary)]"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleAddCoin} className="p-6">
              <div className="mb-4">
                <label className="block text-sm font-medium text-[color:var(--color-text-secondary)] mb-2">Coin Symbol</label>
                <input 
                  type="text" 
                  value={newCoinSymbol}
                  onChange={(e) => setNewCoinSymbol(e.target.value)}
                  placeholder="e.g. LINK, AVAX, MATIC" 
                  className="w-full bg-[var(--color-bg-base)] border border-[var(--color-border)] rounded-lg px-4 py-2.5 text-[color:var(--color-text-primary)] focus:outline-none focus:border-[var(--color-brand)] focus:ring-1 focus:ring-[var(--color-brand)] transition-all uppercase"
                  autoFocus
                />
              </div>
              <div className="flex gap-3 mt-6">
                <button 
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  className="flex-1 py-2.5 bg-[var(--color-bg-hover)] text-[var(--color-text-primary)] rounded-lg font-medium hover:bg-[var(--color-border)] transition-colors"
                >
                  Cancel
                </button>
                <button 
                  type="submit"
                  disabled={!newCoinSymbol.trim()}
                  className="flex-1 py-2.5 bg-[#f0b90b] text-black rounded-lg font-bold hover:bg-[#f0b90b]/90 transition-colors disabled:opacity-50"
                >
                  Add Asset
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
