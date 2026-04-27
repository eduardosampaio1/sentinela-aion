/**
 * Next.js proxy — enforces authentication on all console routes.
 *
 * Public paths (no auth required): /login, /api/auth/*
 * Everything else redirects to /login if session is absent.
 */
export { auth as proxy } from "@/auth";

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     *   - _next/static  (static files)
     *   - _next/image   (image optimization)
     *   - favicon.ico, logo.svg, *.png
     *   - /api/auth/*  (NextAuth endpoints)
     *   - /login        (the login page itself)
     */
    "/((?!_next/static|_next/image|favicon|logo|.*\\.png$|api/auth|login).*)",
  ],
};
