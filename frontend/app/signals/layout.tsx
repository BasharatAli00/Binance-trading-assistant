import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'AI Trading Signals',
  description: 'Actionable AI-driven trading signals, confidence scores, and predicted trends for optimal trading strategies.',
};

export default function SignalsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
