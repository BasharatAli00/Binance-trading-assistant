"use client";

import { Search, Bell, Moon, Sun, Wallet, Menu, PanelLeft, PanelLeftClose } from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useEffect, useState, useRef } from "react";
import { useLayout } from "../context/LayoutContext";
import { useRouter } from "next/navigation";

const SITE_PAGES = [
  { title: "Dashboard", url: "/" },
  { title: "Market Analysis", url: "/analysis" },
  { title: "Portfolio", url: "/portfolio" },
  { title: "Watchlist", url: "/watchlist" },
  { title: "AI Signals", url: "/signals" },
  { title: "News", url: "/news" },
  { title: "Settings", url: "/settings" },
  { title: "Profile", url: "/profile" },
];

export default function TopNavbar() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const { isSidebarCollapsed, toggleSidebar, setMobileMenuOpen } = useLayout();
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [searchResults, setSearchResults] = useState<{title: string, url: string}[]>([]);
  const router = useRouter();
  const searchRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Debounce search query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(searchQuery);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Handle actual search action when debouncedQuery changes
  useEffect(() => {
    if (debouncedQuery.trim()) {
      const lowerQuery = debouncedQuery.toLowerCase();
      const results = SITE_PAGES.filter(page => 
        page.title.toLowerCase().includes(lowerQuery)
      );
      setSearchResults(results);
    } else {
      setSearchResults([]);
    }
  }, [debouncedQuery]);

  // Handle click outside to close search results
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) {
        setSearchResults([]);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleResultClick = (url: string) => {
    router.push(url);
    setSearchQuery("");
    setSearchResults([]);
  };

  return (
    <header className="h-16 fixed top-0 left-0 right-0 bg-[var(--color-bg-base)] border-b border-[var(--color-border)] z-30 flex items-center justify-between px-4 lg:px-6">
      <div className="flex items-center gap-4 lg:gap-10">
        <div className="flex items-center gap-2">
          {/* Mobile Hamburger Menu */}
          <button 
            className="md:hidden p-2 rounded-md hover:bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)]"
            onClick={() => setMobileMenuOpen(true)}
          >
            <Menu className="w-6 h-6" />
          </button>

          {/* Desktop Sidebar Toggle */}
          <button 
            className="hidden md:flex p-2 rounded-md hover:bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)]"
            onClick={toggleSidebar}
          >
            {isSidebarCollapsed ? <PanelLeft className="w-5 h-5" /> : <PanelLeftClose className="w-5 h-5" />}
          </button>
        </div>

        <Link href="/" className="flex items-center gap-3">
          <div className="w-10 h-10 bg-[#f0b90b] rounded-[10px] flex items-center justify-center shadow-md shrink-0">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 3.5 L21 7.5 L12 11.5 L3 7.5 Z" fill="black" />
              <path d="M3 11 L12 15 L21 11 L21 12.5 L12 16.5 L3 12.5 Z" fill="black" />
              <path d="M3 15.5 L12 19.5 L21 15.5 L21 17 L12 21 L3 17 Z" fill="black" />
            </svg>
          </div>
          <div className="flex flex-col justify-center leading-tight">
            <span className="text-[19px] font-bold hidden sm:block text-[color:var(--color-text-primary)] tracking-wide">Binance Trader</span>
            <span className="text-[13px] font-semibold hidden sm:block text-[#0ecb81]">Pro</span>
          </div>
        </Link>

        {/* Search Bar */}
        <div ref={searchRef} className="hidden md:flex items-center bg-[var(--color-bg-hover)] rounded-lg px-3 py-1.5 border border-[var(--color-border)] focus-within:border-[#f0b90b] transition-colors w-64 lg:w-80 ml-4 relative">
          <Search className="w-4 h-4 text-[var(--color-text-secondary)] mr-2 shrink-0" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onFocus={() => {
              if (debouncedQuery.trim()) {
                setSearchResults(SITE_PAGES.filter(p => p.title.toLowerCase().includes(debouncedQuery.toLowerCase())));
              }
            }}
            placeholder="Search pages (Portfolio, News...)"
            className="bg-transparent border-none outline-none text-sm w-full text-[color:var(--color-text-primary)] placeholder-[var(--color-text-secondary)]"
            aria-label="Search pages"
          />
          {searchQuery && (
            <button 
              onClick={() => { setSearchQuery(""); setSearchResults([]); }}
              className="absolute right-3 p-0.5 rounded-full hover:bg-[var(--color-bg-base)] text-[var(--color-text-secondary)] hover:text-[color:var(--color-text-primary)] transition-colors"
              aria-label="Clear search"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          )}

          {/* Search Dropdown Results */}
          {searchResults.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-2 bg-[var(--color-bg-panel)] border border-[var(--color-border)] rounded-lg shadow-xl overflow-hidden z-50">
              <ul className="max-h-64 overflow-y-auto custom-scrollbar py-1">
                {searchResults.map((result, idx) => (
                  <li key={idx}>
                    <button
                      onClick={() => handleResultClick(result.url)}
                      className="w-full text-left px-4 py-2 text-sm text-[color:var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors flex items-center gap-3"
                    >
                      <Search className="w-3 h-3 text-[var(--color-text-secondary)]" />
                      {result.title}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-4 sm:gap-6">
        {/* Wallet Balance */}
        <div className="hidden sm:flex items-center gap-2 text-sm">
          <Wallet className="w-4 h-4 text-[var(--color-text-secondary)]" />
          <span className="text-[var(--color-text-secondary)]">Balance:</span>
          <span className="font-semibold text-[color:var(--color-text-primary)]">$12,450.00</span>
        </div>

        {/* Action Icons */}
        <div className="flex items-center gap-3">
          <button 
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="p-2 rounded-full hover:bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)] transition-colors"
          >
            {mounted && theme === "dark" ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
          </button>
          <button className="p-2 rounded-full hover:bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)] transition-colors relative">
            <Bell className="w-5 h-5" />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-[var(--color-brand)] rounded-full border-2 border-[var(--color-bg-panel)]"></span>
          </button>

          {/* User Profile */}
          <button className="flex items-center gap-2 ml-2 p-1 rounded-full hover:bg-[var(--color-bg-hover)] transition-colors">
            <div className="w-8 h-8 rounded-full bg-gradient-to-r from-blue-500 to-purple-500 flex items-center justify-center text-[color:var(--color-text-primary)] font-medium text-sm">
              A
            </div>
          </button>
        </div>
      </div>
    </header>
  );
}
