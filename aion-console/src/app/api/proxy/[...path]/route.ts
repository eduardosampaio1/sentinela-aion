/**
 * Server-side AION proxy route.
 *
 * All frontend requests go to /api/proxy/<aion-path> instead of the backend
 * directly. This keeps AION_API_KEY out of the browser bundle.
 *
 * Actor identity is forwarded via X-Aion-Actor-* headers so the backend
 * can record who performed each action in the audit trail.
 *
 * Env vars (server-side only, no NEXT_PUBLIC_ prefix):
 *   AION_API_URL   — backend base URL (default: http://localhost:8080)
 *   AION_API_KEY   — service credential sent as Authorization: Bearer <key>
 */
import type { NextRequest } from "next/server";
import { auth } from "@/auth";

export const dynamic = "force-dynamic";

type Params = { path: string[] };

const BACKEND_URL = process.env.AION_API_URL ?? "http://localhost:8080";
const API_KEY = process.env.AION_API_KEY ?? "";

// Headers from the client that should be forwarded to the backend.
// x-aion-actor-reason: human justification required for dangerous mutations
//   (killswitch, promote, rollback, module toggle, LGPD deletion, key rotation).
//   The backend rejects these operations if the header is absent.
const FORWARD_HEADERS = new Set([
  "content-type",
  "x-aion-tenant",
  "x-aion-actor-reason",
  "accept",
  "accept-encoding",
]);

async function proxyRequest(
  request: NextRequest,
  params: Promise<Params>,
): Promise<Response> {
  const { path } = await params;
  const backendPath = "/" + path.join("/");

  // Re-attach query string (e.g. ?format=pdf&days=30)
  const search = request.nextUrl.search;
  const backendUrl = `${BACKEND_URL}${backendPath}${search}`;

  // Build forwarded headers
  const forwardedHeaders: Record<string, string> = {};
  request.headers.forEach((value, key) => {
    if (FORWARD_HEADERS.has(key.toLowerCase())) {
      forwardedHeaders[key] = value;
    }
  });

  // Inject server-side API key — never exposed to browser bundle
  if (API_KEY) {
    forwardedHeaders["Authorization"] = `Bearer ${API_KEY}`;
  }

  // ── Auth gate (C4/N6 fix) ───────────────────────────────────────────────
  // FAIL-CLOSED by default. The AION_API_KEY is admin-level — anything that
  // can hit /api/proxy/* without a session must be rejected before we inject
  // the upstream credential.
  //
  // The only escape hatch is an explicit opt-in env var that does NOT match
  // any common production config — `AION_PROXY_DEV_BYPASS=true`. This is
  // checked alongside `NODE_ENV !== "production"` so a misconfigured prod
  // (NODE_ENV undefined, PM2 without env file, etc.) still gates.
  const session = await auth();
  const allowDevBypass =
    process.env.NODE_ENV !== "production" &&
    process.env.AION_PROXY_DEV_BYPASS === "true";

  if (!session?.user && !allowDevBypass) {
    return new Response(
      JSON.stringify({ error: "Unauthorized", reason: "no_session" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    );
  }
  if (!session?.user && allowDevBypass) {
    // Dev opt-in is loud so we don't silently teach bad habits.
    console.warn(
      "[proxy] DEV BYPASS active (AION_PROXY_DEV_BYPASS=true) — request reaching backend without session",
    );
  }

  // Inject actor identity from the authenticated NextAuth session.
  // These headers let the AION backend record who performed each action.
  if (session?.user) {
    if (session.user.email) {
      forwardedHeaders["X-Aion-Actor-Id"] = session.user.email;
    }
    if (session.user.role) {
      forwardedHeaders["X-Aion-Actor-Role"] = session.user.role;
    }
    if (session.user.provider) {
      forwardedHeaders["X-Aion-Auth-Source"] = session.user.provider;
    }
  }

  // Forward the request body for mutations
  const hasBody =
    request.method !== "GET" && request.method !== "HEAD" && request.method !== "DELETE";

  const upstreamResponse = await fetch(backendUrl, {
    method: request.method,
    headers: forwardedHeaders,
    body: hasBody ? request.body : undefined,
    // @ts-expect-error — Node.js fetch supports duplex for request body streaming
    duplex: hasBody ? "half" : undefined,
  });

  // Pipe response back — preserving status, headers, and body (including binary PDFs)
  const responseHeaders = new Headers();
  upstreamResponse.headers.forEach((value, key) => {
    // Skip hop-by-hop headers
    if (!["connection", "keep-alive", "transfer-encoding"].includes(key.toLowerCase())) {
      responseHeaders.set(key, value);
    }
  });

  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers: responseHeaders,
  });
}

export async function GET(req: NextRequest, ctx: { params: Promise<Params> }) {
  return proxyRequest(req, ctx.params);
}

export async function POST(req: NextRequest, ctx: { params: Promise<Params> }) {
  return proxyRequest(req, ctx.params);
}

export async function PUT(req: NextRequest, ctx: { params: Promise<Params> }) {
  return proxyRequest(req, ctx.params);
}

export async function DELETE(req: NextRequest, ctx: { params: Promise<Params> }) {
  return proxyRequest(req, ctx.params);
}

export async function PATCH(req: NextRequest, ctx: { params: Promise<Params> }) {
  return proxyRequest(req, ctx.params);
}
