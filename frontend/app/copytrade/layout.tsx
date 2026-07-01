import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Smart-Money Copy Trade',
  description: 'Copies top-gainer Solana wallets on multi-wallet consensus (simulated).',
};

export default function CopyTradeLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
