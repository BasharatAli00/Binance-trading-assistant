import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Crypto News',
  description: 'Latest real-time cryptocurrency news, market sentiment, and blockchain updates.',
};

export default function NewsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
