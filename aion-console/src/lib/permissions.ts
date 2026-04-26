/**
 * AION Console — Permission model.
 *
 * Mirrors the backend RBAC but lives in the frontend so the UI can
 * hide/disable controls before the request ever reaches the proxy.
 *
 * Source of truth for backend enforcement is still the AION API key + actor headers.
 * This file controls what the UI shows — not what the backend accepts.
 */
import type { AionRole } from "@/auth";

// ─── Permission keys ──────────────────────────────────────────────────────────

export type Permission =
  // Read
  | "dashboard:read"
  | "sessions:read"
  | "sessions:export"
  | "intelligence:read"
  | "reports:read"
  | "budget:read"
  | "threats:read"
  | "audit:read"
  | "compliance:read"
  // Write — Operator
  | "behavior:write"
  | "routing:write"
  | "shadow:promote"
  | "shadow:rollback"
  | "overrides:write"
  | "budget:write"
  // Write — Admin / Security
  | "killswitch:write"
  | "modules:write"
  | "policies:write"
  | "keys:rotate"
  | "lgpd:delete"
  | "collective:install"
  // Approvals
  | "approvals:resolve"
  | "approvals:read";

// ─── Role → permissions ───────────────────────────────────────────────────────

const ROLE_PERMISSIONS: Record<AionRole, Permission[]> = {
  viewer: [
    "dashboard:read",
    "sessions:read",
    "intelligence:read",
    "reports:read",
    "budget:read",
    "threats:read",
  ],

  analyst: [
    "dashboard:read",
    "sessions:read",
    "sessions:export",
    "intelligence:read",
    "reports:read",
    "budget:read",
    "threats:read",
    "audit:read",
    "compliance:read",
  ],

  auditor: [
    "dashboard:read",
    "sessions:read",
    "sessions:export",
    "intelligence:read",
    "reports:read",
    "budget:read",
    "threats:read",
    "audit:read",
    "compliance:read",
    "approvals:read",
  ],

  security: [
    "dashboard:read",
    "sessions:read",
    "sessions:export",
    "intelligence:read",
    "reports:read",
    "budget:read",
    "threats:read",
    "audit:read",
    "compliance:read",
    "approvals:read",
    "approvals:resolve",
    "killswitch:write",
    "policies:write",
    "lgpd:delete",
  ],

  operator: [
    "dashboard:read",
    "sessions:read",
    "sessions:export",
    "intelligence:read",
    "reports:read",
    "budget:read",
    "budget:write",
    "threats:read",
    "audit:read",
    "compliance:read",
    "approvals:read",
    "approvals:resolve",
    "behavior:write",
    "routing:write",
    "shadow:promote",
    "shadow:rollback",
    "overrides:write",
    "collective:install",
  ],

  admin: [
    // Admin has everything
    "dashboard:read",
    "sessions:read",
    "sessions:export",
    "intelligence:read",
    "reports:read",
    "budget:read",
    "budget:write",
    "threats:read",
    "audit:read",
    "compliance:read",
    "approvals:read",
    "approvals:resolve",
    "behavior:write",
    "routing:write",
    "shadow:promote",
    "shadow:rollback",
    "overrides:write",
    "killswitch:write",
    "modules:write",
    "policies:write",
    "keys:rotate",
    "lgpd:delete",
    "collective:install",
  ],
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

const _cache = new Map<AionRole, Set<Permission>>();

export function getPermissions(role: AionRole): Set<Permission> {
  if (!_cache.has(role)) {
    _cache.set(role, new Set(ROLE_PERMISSIONS[role] ?? []));
  }
  return _cache.get(role)!;
}

export function can(role: AionRole, permission: Permission): boolean {
  return getPermissions(role).has(permission);
}

export function canAny(role: AionRole, permissions: Permission[]): boolean {
  const set = getPermissions(role);
  return permissions.some((p) => set.has(p));
}

/** Human-readable label for each role. */
export const ROLE_LABELS: Record<AionRole, string> = {
  admin: "Admin",
  operator: "Operador",
  analyst: "Analista",
  viewer: "Visualizador",
  auditor: "Auditor",
  security: "Segurança",
};

/** Badge color for each role. */
export const ROLE_COLORS: Record<AionRole, string> = {
  admin: "text-red-400 bg-red-900/30",
  operator: "text-amber-400 bg-amber-900/30",
  analyst: "text-sky-400 bg-sky-900/30",
  viewer: "text-[var(--color-text-muted)] bg-white/5",
  auditor: "text-violet-400 bg-violet-900/30",
  security: "text-orange-400 bg-orange-900/30",
};
