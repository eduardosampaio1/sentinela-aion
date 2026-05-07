/**
 * AION API client — barrel index.
 *
 * All components should import from "@/lib/api" (this file).
 * Domain-specific internals live in sibling files; _core.ts is package-private.
 *
 * Domain modules:
 *   observability — health, stats, events, cache, explain
 *   behavior      — dials, models, module toggles, overrides, hot-reload
 *   protection    — suggestions, calibration, kill switch, threats
 *   sessions      — session list + audit trail
 *   economics     — budget caps, spending, economics summary
 *   intelligence  — NEMOS dashboard, benchmark, recommendations, global feed
 *   admin         — approvals, audit log, key rotation, LGPD deletion
 *   reports       — executive report, schedule
 *   collective    — AION Collective editorial exchange
 */

// Core tenant utils (public)
export { API_BASE, setActiveTenant, getActiveTenant } from "./_core";

// Domain exports
export * from "./observability";
export * from "./behavior";
export * from "./protection";
export * from "./sessions";
export * from "./economics";
export * from "./intelligence";
export * from "./admin";
export * from "./reports";
export * from "./collective";
export * from "./gains";
export * from "./kairos";
