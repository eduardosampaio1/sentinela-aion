"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

export function useKeyboardShortcuts(options: {
  onToggleSidebar?: () => void;
}) {
  const router = useRouter();
  // Keep callback in a ref so the effect doesn't need it as a dependency
  const onToggleSidebarRef = useRef(options.onToggleSidebar);
  onToggleSidebarRef.current = options.onToggleSidebar;

  useEffect(() => {
    const pendingKey = { current: "" };
    let pendingTimer: ReturnType<typeof setTimeout> | null = null;

    const clearPending = () => {
      if (pendingTimer) clearTimeout(pendingTimer);
      pendingKey.current = "";
    };

    const isInputFocused = () => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName.toLowerCase();
      return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
    };

    const handle = (e: KeyboardEvent) => {
      if (isInputFocused()) return;

      // ⌘+/ or Ctrl+/ — toggle sidebar
      if ((e.metaKey || e.ctrlKey) && e.key === "/") {
        e.preventDefault();
        clearPending();
        onToggleSidebarRef.current?.();
        return;
      }

      // Ignore other modifier combos
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // ? — ir para Help
      if (e.key === "?") {
        e.preventDefault();
        clearPending();
        router.push("/help");
        return;
      }

      // Esc — fecha qualquer modal aberto via click fora (dispara blur no elemento ativo)
      if (e.key === "Escape") {
        clearPending();
        return; // modais individuais já escutam Esc
      }

      const key = e.key.toLowerCase();

      // Resolve sequências G+<key>
      if (pendingKey.current === "g") {
        clearPending();
        const routes: Record<string, string> = {
          h: "/",
          o: "/operations",
          r: "/routing",
          p: "/estixe",
          s: "/sessions",
          e: "/budget",
        };
        if (key in routes) {
          e.preventDefault();
          router.push(routes[key]);
        }
        return;
      }

      // Inicia sequência G
      if (key === "g") {
        pendingKey.current = "g";
        pendingTimer = setTimeout(clearPending, 1000);
      }
    };

    document.addEventListener("keydown", handle);
    return () => {
      document.removeEventListener("keydown", handle);
      clearPending();
    };
  }, [router]);
}
