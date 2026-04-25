"use client";

import { useRole } from "@/hooks/use-role";
import type { Permission } from "@/lib/permissions";

interface RestrictedProps {
  /** Permission required to render children. */
  permission: Permission;
  /** Optional alternative content for unauthorized users. */
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Renders children only when the current user has the required permission.
 *
 * Usage:
 *   <Restricted permission="killswitch:write">
 *     <KillswitchButton />
 *   </Restricted>
 *
 *   <Restricted permission="shadow:promote" fallback={<span>Sem permissão</span>}>
 *     <PromoteButton />
 *   </Restricted>
 */
export function Restricted({ permission, fallback = null, children }: RestrictedProps) {
  const { can, loading } = useRole();
  if (loading) return null;
  if (!can(permission)) return <>{fallback}</>;
  return <>{children}</>;
}

/**
 * Like Restricted but accepts multiple permissions — renders if the user has ANY.
 */
export function RestrictedAny({
  permissions,
  fallback = null,
  children,
}: {
  permissions: Permission[];
  fallback?: React.ReactNode;
  children: React.ReactNode;
}) {
  const { canAny, loading } = useRole();
  if (loading) return null;
  if (!canAny(permissions)) return <>{fallback}</>;
  return <>{children}</>;
}
