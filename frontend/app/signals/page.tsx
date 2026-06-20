'use client';
import { useState } from 'react';
import { Brain, TrendingUp, TrendingDown, AlertTriangle, Activity, Zap } from 'lucide-react';

const MOCK_SIGNALS = [
  {
    symbol: 'BTCUSDT',
    action: 'BUY',
    confidence: 87,
    risk: 'LOW',
    trend: 'BULLISH',
    summary: 'AI models detect strong accumulation patterns across multiple timeframes. RSI divergence on the 4H chart combined with a bullish MACD crossover suggests a high probability upward move toward the next resistance level.'
  },
  {
    symbol: 'ETHUSDT',
    action: 'HOLD',
    confidence: 65,
    risk: 'MEDIUM',
    trend: 'NEUTRAL',
    summary: 'Consolidation phase detected. Network activity remains stable, but volume is declining. Recommend waiting for a clear breakout above the current resistance zone before entering new positions.'
  },
  {
    symbol: 'SOLUSDT',
    action: 'SELL',
    confidence: 92,
    risk: 'HIGH',
    trend: 'BEARISH',
    summary: 'Overbought conditions combined with bearish divergence on daily momentum indicators. Sentiment analysis shows a sharp decline in positive mentions. High probability of a short-term correction.'
  }
];

export default function SignalsPage() {
  const [selectedCoin, setSelectedCoin] = useState('BTCUSDT');
  const activeSignal = MOCK_SIGNALS.find(s => s.symbol === selectedCoin) || MOCK_SIGNALS[0];

  return (
    <div className="flex flex-col gap-6">
      <header className="shrink-0 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-3 border-b border-[var(--color-border)]">
        <div className="flex items-center gap-3">
          <Brain className="w-8 h-8 text-[var(--color-brand)]" />
          <h2 className="text-2xl font-bold text-[color:var(--color-text-primary)] tracking-wide">AI Trading Signals</h2>
        </div>

        <div className="flex gap-2 bg-[var(--color-bg-panel)] p-1 rounded-lg border border-[var(--color-border)] overflow-x-auto max-w-full">
          {MOCK_SIGNALS.map(signal => (
            <button
              key={signal.symbol}
              onClick={() => setSelectedCoin(signal.symbol)}
              className={`px-4 py-2 rounded-md font-bold transition-all text-sm whitespace-nowrap ${
                selectedCoin === signal.symbol 
                  ? 'bg-[var(--color-bg-hover)] shadow-sm text-[color:var(--color-text-primary)]' 
                  : 'text-[var(--color-text-secondary)] hover:text-[color:var(--color-text-primary)]'
              }`}
            >
              {signal.symbol.replace('USDT', '')}
            </button>
          ))}
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Main Action Card */}
        <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-xl p-6 shadow-lg flex flex-col items-center justify-center text-center gap-4 lg:col-span-2 relative overflow-hidden">
          <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-[var(--color-brand)] to-transparent opacity-50"></div>
          
          <h3 className="text-[color:var(--color-text-secondary)] text-sm font-bold uppercase tracking-widest">Recommended Action</h3>
          
          <div className="flex items-center gap-4 mt-2">
            {activeSignal.action === 'BUY' && <TrendingUp className="w-12 h-12 text-[#00ff88]" />}
            {activeSignal.action === 'SELL' && <TrendingDown className="w-12 h-12 text-[#ff4466]" />}
            {activeSignal.action === 'HOLD' && <Activity className="w-12 h-12 text-[#f0b90b]" />}
            
            <span className={`text-6xl font-extrabold tracking-tight ${
              activeSignal.action === 'BUY' ? 'text-[#00ff88]' : 
              activeSignal.action === 'SELL' ? 'text-[#ff4466]' : 
              'text-[#f0b90b]'
            }`}>
              {activeSignal.action}
            </span>
          </div>
          <p className="text-[color:var(--color-text-primary)] mt-4 max-w-md">
            Based on multi-factor AI analysis for {activeSignal.symbol}
          </p>
        </div>

        {/* Quick Stats Grid */}
        <div className="grid grid-rows-3 gap-4">
          <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-xl p-4 shadow-sm flex items-center justify-between group hover:border-[var(--color-brand)] transition-colors">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-[var(--color-bg-hover)] rounded-lg text-[var(--color-brand)]">
                <Zap className="w-5 h-5" />
              </div>
              <span className="text-[color:var(--color-text-secondary)] font-medium">Confidence</span>
            </div>
            <span className="text-2xl font-bold text-[color:var(--color-text-primary)]">{activeSignal.confidence}%</span>
          </div>

          <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-xl p-4 shadow-sm flex items-center justify-between group hover:border-[var(--color-brand)] transition-colors">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-[var(--color-bg-hover)] rounded-lg text-[var(--color-brand)]">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <span className="text-[color:var(--color-text-secondary)] font-medium">Risk Level</span>
            </div>
            <span className={`text-xl font-bold ${
              activeSignal.risk === 'LOW' ? 'text-[#00ff88]' : 
              activeSignal.risk === 'HIGH' ? 'text-[#ff4466]' : 
              'text-[#f0b90b]'
            }`}>{activeSignal.risk}</span>
          </div>

          <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-xl p-4 shadow-sm flex items-center justify-between group hover:border-[var(--color-brand)] transition-colors">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-[var(--color-bg-hover)] rounded-lg text-[var(--color-brand)]">
                <Activity className="w-5 h-5" />
              </div>
              <span className="text-[color:var(--color-text-secondary)] font-medium">Predicted Trend</span>
            </div>
            <span className={`text-xl font-bold ${
              activeSignal.trend === 'BULLISH' ? 'text-[#00ff88]' : 
              activeSignal.trend === 'BEARISH' ? 'text-[#ff4466]' : 
              'text-[#f0b90b]'
            }`}>{activeSignal.trend}</span>
          </div>
        </div>

        {/* AI Analysis Summary */}
        <div className="bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-xl p-6 shadow-lg lg:col-span-3">
          <div className="flex items-center gap-3 mb-4">
            <Brain className="w-6 h-6 text-[var(--color-brand)]" />
            <h3 className="text-lg font-bold text-[color:var(--color-text-primary)]">AI Analysis Summary</h3>
          </div>
          <div className="bg-[var(--color-bg-hover)] p-5 rounded-lg border border-[var(--color-border)]">
            <p className="text-[color:var(--color-text-primary)] leading-relaxed text-lg">
              {activeSignal.summary}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
