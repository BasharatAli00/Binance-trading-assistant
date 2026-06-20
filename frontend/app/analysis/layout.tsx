import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Market Analysis',
  description: 'In-depth market analysis, technical indicators, and on-chain data for cryptocurrencies.',
};

export default function AnalysisLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
