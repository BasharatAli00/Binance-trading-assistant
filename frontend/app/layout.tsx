import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "./components/ThemeProvider";
import { LayoutProvider } from "./context/LayoutContext";
import AppShell from "./components/AppShell";
import AuthProvider from "./components/AuthProvider";

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
    template: '%s | Nexus Trading Terminal',
    default: 'Nexus Trading Terminal - AI Assistant',
  },
  description: "Advanced AI-powered Trading Terminal featuring real-time market analysis, interactive candlestick charts, and intelligent trading signals.",
  keywords: ["Trading Terminal", "Market Analysis", "AI Trading", "Market Signals", "Blockchain", "Technical Analysis"],
  openGraph: {
    title: 'Nexus Trading Terminal',
    description: 'Advanced AI-powered Trading Terminal featuring real-time market analysis, interactive candlestick charts, and intelligent trading signals.',
    type: 'website',
    siteName: 'Nexus Trading Terminal',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Nexus Trading Terminal',
    description: 'Advanced AI-powered Trading Terminal.',
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
            <AuthProvider>
              <AppShell>{children}</AppShell>
            </AuthProvider>
          </LayoutProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
