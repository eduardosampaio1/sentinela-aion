# ADR-003: S2 Architecture Decisions (F-13, F-21, F-25, F-26, F-27)

**Date:** 2026-05-15
**Status:** Accepted
**Context:** QA Ceifador audit S2 findings requiring architecture/product decisions.
**Constraint:** Sentinela AION runs on client infrastructure (cloud + on-prem). Simpler, more secure, and less costly is always the guiding principle. Single-tenant per deployment.

---

## F-13: X-Aion-Actor-Role — Keep Plain Header (REJECTED)

**Finding:** Audit recommended JWT-based role assertion instead of plain HTTP header.

**Decision:** Reject. Keep plain header. Auth is done via HMAC API key validation (`key:role:tenants`). The `X-Aion-Actor-Role` header is informational only — used for audit trail correlation, never for authorization decisions.

**Mitigation implemented:** Middleware logs a warning when the header value diverges from the resolved key role, alerting operators to misconfigured clients or escalation attempts.

**Rationale:** JWT would require signing key management on client infra, add a verification step for a value never used for authz, and create misleading security theater.

---

## F-21: Behavior Dial — Allowlist Validation (PARTIAL ACCEPT)

**Finding:** Behavior dial uses prompt engineering internally, described as "prompt injection by design."

**Decision:** Keep prompt-based approach (architecturally sound for tone/style control). Add strict input validation: `cost_target` now uses `Literal["free", "low", "medium", "high", "fast"]` instead of free string. All integer dials already use Pydantic `ge=0, le=100` bounds. `StrictModel(extra="forbid")` blocks unknown fields.

**Rationale:** Parametric control sounds clean but maps back to prompt fragments anyway. The real risk is freeform input escaping scope — validation boundary eliminates this.

---

## F-25: Cache — Keep In-Process LRU (REJECTED)

**Finding:** Audit recommended distributed Redis cache for consistency across replicas.

**Decision:** Reject. In-process LRU cache is correct for single-tenant, 1-2 replica deployments. Cache inconsistency between replicas results only in a cache miss (re-computation), not stale data.

**Rationale:** Redis cache adds: another service to deploy/monitor/patch, network latency on every hit, a new failure mode, and cost — all for near-zero benefit in this architecture.

**Future:** If multi-replica requirements emerge, introduce Redis cache as opt-in behind an abstraction. Do not pre-build.

---

## F-26: Tenant Label in Prometheus — Not Applicable (REJECTED)

**Finding:** Audit recommended tenant dimension in Prometheus metrics.

**Decision:** Reject. Single-tenant per deployment means every metric already belongs to one tenant. A tenant label adds cardinality cost with zero analytical value.

**Rationale:** The standard Prometheus `instance` label is sufficient for operators managing multiple client deployments from a central dashboard.

**Future:** If multi-tenant is ever needed, adding a label is a 30-minute change.

---

## F-27: Adversarial Eval Suite — Implement Incrementally (ACCEPTED)

**Finding:** No formal adversarial test suite with FP/TP baseline.

**Decision:** Accept. A governance engine must prove adversarial resilience.

**Phase 1 (this commit):** 25 test cases in `tests/test_adversarial.py` covering:
- Behavior dial injection (freeform strings, overflow, extra fields)
- RBAC boundary violations (role escalation, cross-tenant, forged headers)
- Encoding tricks (unicode, homoglyphs, null bytes, path traversal)
- Policy edge cases (empty messages, payload limits, legacy key rejection)

**Phase 2 (future):** Expand to 50+ cases with open-source prompt injection datasets, establish confusion matrix baseline, CI regression gate.

**Phase 3 (ongoing):** Every production incident becomes a new test case.
