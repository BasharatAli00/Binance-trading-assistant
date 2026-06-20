"use client";

import React from "react";
import { useLayout } from "../context/LayoutContext";
import TopNavbar from "./TopNavbar";
import Sidebar from "./Sidebar";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { isSidebarCollapsed } = useLayout();

  return (
    <>
      <TopNavbar />
      <div className="flex flex-1 pt-16 h-screen overflow-hidden">
        <Sidebar />
        <main
          className={`flex-1 overflow-y-auto custom-scrollbar transition-all duration-300 ${
            isSidebarCollapsed ? "md:ml-20" : "md:ml-64"
          } p-4 lg:p-6 w-full`}
        >
          {children}
        </main>
      </div>
    </>
  );
}
