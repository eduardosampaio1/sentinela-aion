/**
 * Next.js proxy — enforces authentication on HTML console routes.
 *
 * Public paths (no auth required): /login, /api/auth/*
 * /api/proxy/*  is explicitly excluded so it falls through to its own
 * route handler (src/app/api/proxy/[...path]/route.ts), which returns a
 * proper 401 JSON instead of a 302 HTML redirect to /login (a client
 * fetch() would silently follow the redirect and try to JSON-parse the
 * HTML login page, which is the worst kind of failure mode).
 *
 * Defense-in-depth: route.ts also gates the request explicitly. If this
 * matcher is ever broadened to cover /api/proxy/* again, the route handler
 * still rejects unauthenticated calls.
 */
export { auth as proxy } from "@/auth";

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     *   - _next/static  (static files)
     *   - _next/image   (image optimization)
     *   - favicon.ico, *.png, *.svg, *.ico
     *   - /api/auth/...  (NextAuth endpoints)
     *   - /api/proxy/... (handled by the proxy route's own auth gate)
     *   - /login         (the login page itself — exact prefix only,
     *                     followed by `/`, end-of-string, or `?`)
     *
     * The trailing path delimiters (`/`, `$`, `?`) prevent the matcher
     * from accidentally excluding routes that merely START with one of
     * these names (e.g. `/login-help`, `/api/proxytools`). Without them
     * a future `/loginsomething` page would silently bypass auth.
     */
    "/((?!_next/static(?:/|$)|_next/image(?:/|$)|favicon\\.ico|.*\\.(?:png|svg|ico)$|api/auth(?:/|$)|api/proxy(?:/|$)|login(?:/|$|\\?)|login$).*)",
  ],
};
