// AION API Types — matches backend schemas

export type ServiceStatus = "online" | "offline" | "degraded";

export interface Stats {
  total_requests: number;
  bypasses: number;
  routes: number;
  blocks: number;
  errors: number;
  tokens_saved: number;
  cost_saved: number;
  avg_latency_ms: number;
  top_model: string;
}

export interface AionEvent {
  id: string;
  timestamp: string;
  tenant: string;
  input: string;
  decision: "bypass" | "route" | "block" | "fallback" | "error";
  module: "ESTIXE" | "NOMOS" | "METIS" | null;
  policy_applied: string | null;
  model_used: string | null;
  tokens_used: number | null;
  cost: number | null;
  response_time_ms: number;
  error: string | null;
  output: string | null;
}

export interface BehaviorDial {
  objectivity: number;
  verbosity: number;
  economy: number;
  explanation: number;
  confidence: number;
  safe_mode: number;
  formality: number;
}

export interface ModelInfo {
  id: string;
  provider: string;
  // Below: optional so the UI gracefully handles a minimal {id, provider}
  // payload (e.g. a backend that only knows the configured default model).
  name?: string;
  cost_input_per_1m?: number;
  cost_output_per_1m?: number;
  max_tokens?: number;
  latency_ms?: number;
  capabilities?: string[];
  // "active"   — has credential + circuit breaker healthy
  // "fallback" — has credential but enabled=false in YAML (opt-out backup)
  // "inactive" — no credential provisioned for the provider
  // "error"    — circuit breaker is currently OPEN
  status?: "active" | "inactive" | "fallback" | "error";
  /** True when this model matches the backend's `default_model` setting. */
  is_default?: boolean;
}

export interface RoutingRule {
  id: string;
  prompt_type: string;
  model_id: string;
  condition: string;
}

export interface IntentCategory {
  id: string;
  name: string;
  enabled: boolean;
  examples: string[];
  response: string;
}

export interface BlockCategory {
  id: string;
  name: string;
  enabled: boolean;
  severity: "critical" | "high" | "medium";
  examples: string[];
  response: string; // mensagem exibida ao usuário quando bloqueado
}

export interface SecurityRule {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  severity: "critical" | "high" | "medium" | "low";
}

export interface PolicyRule {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  action: "block" | "warn" | "sanitize";
}

export interface IntentSuggestion {
  id: string;
  cluster_size: number;
  sample_messages: string[];
  suggested_intent_name: string;
  suggested_response: string;
  estimated_daily_savings: number;
  avg_response_length: number;
  confidence: number;
}

export interface SuggestionsResponse {
  tenant: string;
  total_samples: number;
  suggestions: IntentSuggestion[];
  count: number;
}

export interface SuggestionApprovalResponse {
  status: string;
  suggestion_id: string;
  intent_name: string;
  response: string;
  yaml_snippet: string;
  note: string;
}

export interface CacheStats {
  enabled: boolean;
  hits: number;
  misses: number;
  hit_rate: number;
  invalidations: number;
  evictions: number;
  total_entries: number;
  entries_by_tenant: Record<string, number>;
}

export type ApprovalStatus =
  | "draft"
  | "pending_review"
  | "approved_pm"
  | "approved_tech"
  | "ready_prod"
  | "live"
  | "rejected";

// ─── Sessions ───────────────────────────────────────────────────────────────

export interface SessionTurn {
  turn: number;
  timestamp: string;
  input: string;
  decision: "bypass" | "route" | "block" | "fallback";
  module: "ESTIXE" | "NOMOS" | "METIS" | null;
  model_used: string | null;
  latency_ms: number;
  cost?: number;             // not available from real TurnAuditEntry — LGPD constraint
  risk_score: number;
  // Response fields — only in mock/demo; backend does not store LLM responses
  aion_response?: string;
  llm_response?: string;
  block_reason?: string;
  pii_detected?: string[];   // PII encontrado neste turno
  metis_compressed?: boolean; // METIS comprimiu o contexto
}

export interface Session {
  id: string;
  user_hash: string;
  tenant: string;
  turns: number;
  started_at: string;
  last_activity: string;
  // Derived from audit trail — undefined until getSessionAudit() is called
  risk?: "low" | "medium" | "high" | "critical";
  spend?: number;
  outcome?: "bypassed" | "routed" | "blocked" | "optimized";
  hmac_valid?: boolean;
  turn_history?: SessionTurn[];
}

// ─── Budget ─────────────────────────────────────────────────────────────────

export interface BudgetCap {
  department: string;
  cap_brl: number;
  used_brl: number;
  used_pct: number;
  mode: "downgrade" | "hard_stop" | "alert_only";
  alert_sent: boolean;
}

export interface BudgetSummary {
  monthly_budget: number;
  used_brl: number;
  used_pct: number;
  avoided_cost: number;
  alerts: number;
  downgrades: number;
  caps: BudgetCap[];
}

// ─── Admin ───────────────────────────────────────────────────────────────────

export interface AdminRole {
  name: string;
  users: number;
  permissions: string[];
  color: string;
}

export interface IdentityProvider {
  name: string;
  type: string;
  status: "connected" | "pending" | "error";
  users: number;
}

// ─── Threat categories (ESTIXE) ──────────────────────────────────────────────

export interface ThreatCategory {
  name: string;
  count: number;
  pct: number;
  action: "block" | "sanitize" | "warn";
}

// ─── Intent performance (NOMOS / NEMOS IntentMemory) ─────────────────────────
// Schema matches GET /v1/intelligence/{tenant}/intents
// NOTE: current_model, best_model, savings_day are model-level metrics —
// they are NOT tracked per-intent in the current NEMOS schema.

export interface IntentPerformance {
  name: string;
  requests: number;                  // total_seen
  bypassed?: number;                 // bypassed_count
  forwarded?: number;                // forwarded_count
  bypass_success_rate?: number;      // 0.0–1.0
  avg_cost_when_forwarded?: number;  // USD average
  followup_rate?: number;            // 0.0–1.0
  confidence: string;                // "none" | "low" | "medium" | "high"
}

// ─── Charts ───────────────────────────────────────────────────────────────────

export interface SpendTrendPoint {
  date: string;
  spend: number;
  avoided: number;
}

// ─── Monitors (Operations) ───────────────────────────────────────────────────

export type MonitorStatus = "ok" | "triggered" | "no_data";

export interface MonitorAlert {
  hour: number; // 0 = oldest, 23 = most recent
  status: MonitorStatus;
}

export interface Monitor {
  id: string;
  name: string;
  description: string;
  metric: string;
  unit: string;
  threshold: number;
  threshold_direction: "above" | "below"; // alert when value is above/below threshold
  current_value: number;
  status: MonitorStatus;
  last_triggered: string | null;
  alert_history: MonitorAlert[]; // 24 hourly data points
}

// ─── Annotations (Sessions) ───────────────────────────────────────────────────

export interface AnnotationItem {
  id: string;
  session_id: string;
  turn: number;
  prompt: string;
  decision: "bypass" | "route" | "block";
  aion_response?: string;
  block_reason?: string;
  model_used?: string;
  flagged_reason: string;
  annotated: boolean;
  decision_correct?: boolean;
  false_positive?: boolean;
  response_adequate?: boolean;
  comment?: string;
}

// ─── AION Collective (Editorial Exchange) ────────────────────────────────────

export interface PolicyProvenance {
  version: string;
  last_updated: string;
  author: string;
  signed_by_aion: boolean;
  changelog: string[];
}

export interface CollectivePolicyMetrics {
  installs_production: number;
  avg_savings_pct: number;
  avg_latency_change_ms: number;
  false_positive_rate: number;
  rollback_rate: number;
  confidence_score: number;
}

export interface CollectivePolicy {
  id: string;
  name: string;
  description: string;
  sectors: string[];
  editorial: boolean;
  risk_level: "low" | "medium" | "high";
  reversible: boolean;
  provenance: PolicyProvenance;
  metrics: CollectivePolicyMetrics;
  installed_status?: "sandbox" | "shadow" | "production" | null;
}

export interface InstalledCollectivePolicy {
  policy_id: string;
  name: string;
  version: string;
  status: "sandbox" | "shadow" | "production";
  installed_at: number;
  sectors: string[];
}
