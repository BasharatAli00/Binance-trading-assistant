import { Search, Bell, Moon, Sun, Wallet } from "lucide-react";
import Link from "next/link";

export default function TopNavbar() {
  return (
    <header className="h-16 fixed top-0 left-0 right-0 bg-[#181a20] border-b border-[var(--color-border)] z-20 flex items-center justify-between px-4 lg:px-6">
      <div className="flex items-center gap-10">
        <Link href="/" className="flex items-center gap-3">
          <div className="w-10 h-10 bg-[#f0b90b] rounded-[10px] flex items-center justify-center shadow-md shrink-0">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 3.5 L21 7.5 L12 11.5 L3 7.5 Z" fill="black"/>
              <path d="M3 11 L12 15 L21 11 L21 12.5 L12 16.5 L3 12.5 Z" fill="black"/>
              <path d="M3 15.5 L12 19.5 L21 15.5 L21 17 L12 21 L3 17 Z" fill="black"/>
            </svg>
          </div>
          <div className="flex flex-col justify-center leading-tight">
            <span className="text-[19px] font-bold hidden sm:block text-white tracking-wide">Binance Trader</span>
            <span className="text-[13px] font-semibold hidden sm:block text-[#0ecb81]">Pro</span>
          </div>
        </Link>

        {/* Search Bar */}
        <div className="hidden md:flex items-center bg-[#0b0e11] rounded-lg px-3 py-1.5 border border-[#2b3139] focus-within:border-[#f0b90b] transition-colors w-64 lg:w-80 ml-4">
          <Search className="w-4 h-4 text-[#848e9c] mr-2" />
          <input
            type="text"
            placeholder="Search coins (BTC, ETH...)"
            className="bg-transparent border-none outline-none text-sm w-full text-white placeholder-[#848e9c]"
          />
        </div>
      </div>

      <div className="flex items-center gap-4 sm:gap-6">
        {/* Wallet Balance */}
        <div className="hidden sm:flex items-center gap-2 text-sm">
          <Wallet className="w-4 h-4 text-[var(--color-text-secondary)]" />
          <span className="text-[var(--color-text-secondary)]">Balance:</span>
          <span className="font-semibold text-white">$12,450.00</span>
        </div>

        {/* Action Icons */}
        <div className="flex items-center gap-3">
          <button className="p-2 rounded-full hover:bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)] transition-colors">
            <Sun className="w-5 h-5" />
          </button>
          <button className="p-2 rounded-full hover:bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)] transition-colors relative">
            <Bell className="w-5 h-5" />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-[var(--color-brand)] rounded-full border-2 border-[var(--color-bg-panel)]"></span>
          </button>

          {/* User Profile */}
          <button className="flex items-center gap-2 ml-2 p-1 rounded-full hover:bg-[var(--color-bg-hover)] transition-colors">
            <div className="w-8 h-8 rounded-full bg-gradient-to-r from-blue-500 to-purple-500 flex items-center justify-center text-white font-medium text-sm">
              U
            </div>
          </button>
        </div>
      </div>
    </header>
  );
}
