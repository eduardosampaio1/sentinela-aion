"use client";

import { useState, type ReactNode } from "react";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";
import { useKeyboardShortcuts } from "@/lib/hooks/use-keyboard-shortcuts";

export function Shell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  useKeyboardShortcuts({ onToggleSidebar: () => setCollapsed((v) => !v) });

  return (
    <div className="h-full">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
      <Topbar collapsed={collapsed} />
      <main
        className={`pt-14 transition-all duration-200 ${
          collapsed ? "pl-16" : "pl-60"
        }`}
      >
        <div className="mx-auto max-w-7xl p-6">
          {children}
        </div>
      </main>
    </div>
  );
}
