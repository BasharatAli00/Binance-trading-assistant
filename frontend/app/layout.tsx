import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "./components/ThemeProvider";
import { LayoutProvider } from "./context/LayoutContext";
import AppShell from "./components/AppShell";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    template: '%s | Binance Trader Pro',
    default: 'Binance AI Trading Assistant',
  },
  description: "Advanced AI-powered Binance Trading Assistant featuring real-time market analysis, interactive candlestick charts, and intelligent trading signals.",
  keywords: ["Binance", "Trading Bot", "Crypto Analysis", "AI Trading", "Market Signals", "Blockchain", "Technical Analysis"],
  openGraph: {
    title: 'Binance AI Trading Assistant',
    description: 'Advanced AI-powered Binance Trading Assistant featuring real-time market analysis, interactive candlestick charts, and intelligent trading signals.',
    type: 'website',
    siteName: 'Binance Trader Pro',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Binance AI Trading Assistant',
    description: 'Advanced AI-powered Binance Trading Assistant.',
  }
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col bg-[var(--color-bg-base)] text-[color:var(--color-text-primary)]">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
          <LayoutProvider>
            <AppShell>{children}</AppShell>
          </LayoutProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
