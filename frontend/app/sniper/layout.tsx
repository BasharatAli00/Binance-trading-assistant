import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Intelligent Sniper',
  description: 'ML-powered pump.fun Solana meme-coin trading bot (simulated).',
};

export default function SniperLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
