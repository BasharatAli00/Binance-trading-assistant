import type { Metadata } from 'next';
import LiquidityPoolView from '../components/LiquidityPoolView';

export const metadata: Metadata = {
  title: 'Liquidity Pool | Binance Trader Pro',
  description:
    '5-minute candlestick chart for memecoin Commander VRAX on Robinhood Chain with 1h & 5m liquidity pools and sweep detection.',
};

export default function LiquidityPage() {
  return <LiquidityPoolView />;
}
