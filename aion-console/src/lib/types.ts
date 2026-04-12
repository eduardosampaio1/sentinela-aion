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
  name: string;
  cost_input_per_1m: number;
  cost_output_per_1m: number;
  max_tokens: number;
  latency_ms: number;
  capabilities: string[];
  status: "active" | "inactive" | "fallback";
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

export type ApprovalStatus =
  | "draft"
  | "pending_review"
  | "approved_pm"
  | "approved_tech"
  | "ready_prod"
  | "live"
  | "rejected";
