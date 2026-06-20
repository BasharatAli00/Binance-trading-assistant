import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Watchlist',
  description: 'Track your favorite cryptocurrency assets in real-time.',
};

export default function WatchlistLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
