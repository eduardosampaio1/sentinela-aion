"use client";

import { useSession } from "next-auth/react";
import { can, canAny, getPermissions } from "@/lib/permissions";
import type { AionRole } from "@/auth";
import type { Permission } from "@/lib/permissions";

/**
 * Hook that exposes the current user's role and permission checks.
 *
 * Usage:
 *   const { role, can, loading } = useRole();
 *   if (!can("killswitch:write")) return null;
 *
 * Falls back to "viewer" when session is loading or absent (never grants extra access).
 */
export function useRole() {
  const { data: session, status } = useSession();
  const loading = status === "loading";
  const role: AionRole = (session?.user?.role as AionRole) ?? "viewer";

  return {
    role,
    loading,
    user: session?.user ?? null,
    can: (permission: Permission) => can(role, permission),
    canAny: (permissions: Permission[]) => canAny(role, permissions),
    permissions: getPermissions(role),
  };
}
