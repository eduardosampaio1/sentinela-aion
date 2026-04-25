/**
 * NextAuth v5 configuration — AION Console identity layer.
 *
 * Providers configured via env vars (see .env.example).
 * Role resolution order:
 *   1. AION_ROLE_MAP (email:role pairs) — explicit override per user
 *   2. AION_ADMIN_EMAILS — comma-separated list → role "admin"
 *   3. AION_DEFAULT_ROLE — fallback for any authenticated user (default: "viewer")
 *
 * Supported roles: admin | operator | analyst | viewer | auditor | security
 */
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";
import type { Session } from "next-auth";

export type AionRole =
  | "admin"
  | "operator"
  | "analyst"
  | "viewer"
  | "auditor"
  | "security";

/** Extend NextAuth session with AION-specific fields. */
declare module "next-auth" {
  interface Session {
    user: {
      name?: string | null;
      email?: string | null;
      image?: string | null;
      role: AionRole;
      provider: string;
    };
  }
}

// ─── Role resolution ──────────────────────────────────────────────────────────

const ROLE_MAP: Record<string, AionRole> = {};

const rawMap = process.env.AION_ROLE_MAP ?? "";
for (const pair of rawMap.split(",")) {
  const [email, role] = pair.split(":").map((s) => s.trim());
  if (email && role) ROLE_MAP[email.toLowerCase()] = role as AionRole;
}

const ADMIN_EMAILS = new Set(
  (process.env.AION_ADMIN_EMAILS ?? "").split(",").map((e) => e.trim().toLowerCase()).filter(Boolean),
);

const DEFAULT_ROLE: AionRole = (process.env.AION_DEFAULT_ROLE as AionRole) ?? "viewer";

function resolveRole(email: string | null | undefined): AionRole {
  if (!email) return DEFAULT_ROLE;
  const lower = email.toLowerCase();
  if (ROLE_MAP[lower]) return ROLE_MAP[lower];
  if (ADMIN_EMAILS.has(lower)) return "admin";
  return DEFAULT_ROLE;
}

// ─── Providers ────────────────────────────────────────────────────────────────

const providers = [];

if (process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET) {
  providers.push(
    Google({
      clientId: process.env.AUTH_GOOGLE_ID,
      clientSecret: process.env.AUTH_GOOGLE_SECRET,
    }),
  );
}

if (process.env.AUTH_ENTRA_ID && process.env.AUTH_ENTRA_SECRET) {
  providers.push(
    MicrosoftEntraID({
      clientId: process.env.AUTH_ENTRA_ID,
      clientSecret: process.env.AUTH_ENTRA_SECRET,
      // issuer customizes the tenant; common = multi-tenant, or use specific tenant GUID
      issuer: process.env.AUTH_ENTRA_TENANT_ID
        ? `https://login.microsoftonline.com/${process.env.AUTH_ENTRA_TENANT_ID}/v2.0`
        : "https://login.microsoftonline.com/common/v2.0",
    }),
  );
}

// ─── Export ───────────────────────────────────────────────────────────────────

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers,
  pages: {
    signIn: "/login",
    error: "/login",
  },
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        token.provider = account.provider;
        token.role = resolveRole(token.email);
      }
      return token;
    },
    async session({ session, token }) {
      session.user.role = (token.role as AionRole) ?? DEFAULT_ROLE;
      session.user.provider = (token.provider as string) ?? "unknown";
      return session;
    },
  },
  secret: process.env.AUTH_SECRET,
});
