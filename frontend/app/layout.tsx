import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import TopNavbar from "./components/TopNavbar";
import Sidebar from "./components/Sidebar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Binance AI Trading Assistant",
  description: "Modern, production-ready Binance Trading Assistant",
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
    >
      <body className="min-h-full flex flex-col bg-[var(--color-bg-base)] text-white">
        <TopNavbar />
        <div className="flex flex-1 pt-16">
          <Sidebar />
          <main className="flex-1 md:ml-64 p-4 lg:p-6 overflow-y-auto custom-scrollbar">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
