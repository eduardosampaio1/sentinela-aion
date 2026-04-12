"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  SlidersHorizontal,
  GitBranch,
  Shield,
  Radio,
  Settings,
  HelpCircle,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { Logo } from "./logo";

const navItems = [
  { href: "/", label: "Visão Geral", icon: Activity },
  { href: "/policies", label: "Comportamento", icon: SlidersHorizontal },
  { href: "/routing", label: "Roteamento", icon: GitBranch },
  { href: "/estixe", label: "Proteção", icon: Shield },
  { href: "/operations", label: "Operação", icon: Radio },
];

const bottomItems = [
  { href: "/settings", label: "Configurações", icon: Settings },
  { href: "/help", label: "Ajuda", icon: HelpCircle },
];

export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  return (
    <aside
      className={`fixed left-0 top-0 z-20 flex h-full flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)] transition-all duration-200 ${
        collapsed ? "w-16" : "w-60"
      }`}
    >
      {/* Header */}
      <div className="flex h-14 items-center gap-3 border-b border-[var(--color-border)] px-4">
        <Logo size={28} />
        {!collapsed && (
          <span className="font-[family-name:var(--font-heading)] text-sm font-bold text-[var(--color-primary)]">
            Sentinela AION
          </span>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-1 px-2 py-4">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors duration-150 ${
                active
                  ? "bg-[var(--color-primary)]/10 text-[var(--color-primary)]"
                  : "text-[var(--color-text-muted)] hover:bg-white/5 hover:text-[var(--color-text)]"
              } ${collapsed ? "justify-center" : ""}`}
              title={collapsed ? item.label : undefined}
            >
              <Icon className="h-5 w-5 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Bottom */}
      <div className="space-y-1 border-t border-[var(--color-border)] px-2 py-4">
        {bottomItems.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-[var(--color-text-muted)] transition-colors duration-150 hover:bg-white/5 hover:text-[var(--color-text)] ${
                collapsed ? "justify-center" : ""
              }`}
              title={collapsed ? item.label : undefined}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );
        })}

        {/* Collapse toggle */}
        <button
          onClick={onToggle}
          className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-[var(--color-text-muted)] transition-colors duration-150 hover:bg-white/5 hover:text-[var(--color-text)] cursor-pointer ${
            collapsed ? "justify-center" : ""
          }`}
          aria-label={collapsed ? "Expandir menu" : "Recolher menu"}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <>
              <PanelLeftClose className="h-4 w-4" />
              <span>Recolher</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
