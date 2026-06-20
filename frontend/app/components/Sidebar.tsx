"use client";

import Link from "next/link";
import {
  LayoutDashboard,
  PieChart,
  Star,
  Activity,
  BarChart2,
  Newspaper,
  Settings,
  User,
  LogOut,
  X,
} from "lucide-react";
import { useLayout } from "../context/LayoutContext";

const navItems = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Market Analysis", href: "/analysis", icon: BarChart2 },
  { name: "Portfolio", href: "/portfolio", icon: PieChart },
  { name: "Watchlist", href: "/watchlist", icon: Star },
  { name: "AI Signals", href: "/signals", icon: Activity },
  { name: "News", href: "/news", icon: Newspaper },
];

const bottomNavItems = [
  { name: "Settings", href: "/settings", icon: Settings },
  { name: "Profile", href: "/profile", icon: User },
];

export default function Sidebar() {
  const { isSidebarCollapsed, isMobileMenuOpen, setMobileMenuOpen } = useLayout();

  const sidebarWidth = isSidebarCollapsed ? "w-20" : "w-64";

  return (
    <>
      {/* Mobile Overlay */}
      {isMobileMenuOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden transition-opacity"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={`fixed inset-y-0 left-0 top-16 bg-[var(--color-bg-panel)] border-r border-[var(--color-border)] flex flex-col z-50 transform transition-all duration-300 ease-in-out md:translate-x-0 ${
          isMobileMenuOpen ? "translate-x-0 w-64" : "-translate-x-full md:w-auto"
        } ${sidebarWidth}`}
      >
        <div className="flex-1 py-6 space-y-1 overflow-y-auto custom-scrollbar px-3">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.name}
                href={item.href}
                className="flex items-center gap-4 px-3 py-3 rounded-lg text-[var(--color-text-secondary)] hover:text-[color:var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors group"
                title={isSidebarCollapsed ? item.name : undefined}
                onClick={() => setMobileMenuOpen(false)}
              >
                <Icon className="w-5 h-5 shrink-0 group-hover:text-[var(--color-brand)] transition-colors" />
                {!isSidebarCollapsed && (
                  <span className="font-medium text-sm whitespace-nowrap">{item.name}</span>
                )}
              </Link>
            );
          })}
        </div>

        <div className="p-3 border-t border-[var(--color-border)] space-y-1">
          {bottomNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.name}
                href={item.href}
                className="flex items-center gap-4 px-3 py-3 rounded-lg text-[var(--color-text-secondary)] hover:text-[color:var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors group"
                title={isSidebarCollapsed ? item.name : undefined}
                onClick={() => setMobileMenuOpen(false)}
              >
                <Icon className="w-5 h-5 shrink-0 group-hover:text-[var(--color-brand)] transition-colors" />
                {!isSidebarCollapsed && (
                  <span className="font-medium text-sm whitespace-nowrap">{item.name}</span>
                )}
              </Link>
            );
          })}
          <button 
            className="w-full flex items-center gap-4 px-3 py-3 rounded-lg text-[var(--color-text-secondary)] hover:text-[var(--color-danger)] hover:bg-[var(--color-bg-hover)] transition-colors group"
            title={isSidebarCollapsed ? "Logout" : undefined}
          >
            <LogOut className="w-5 h-5 shrink-0" />
            {!isSidebarCollapsed && (
              <span className="font-medium text-sm whitespace-nowrap">Logout</span>
            )}
          </button>
        </div>
      </aside>
    </>
  );
}
