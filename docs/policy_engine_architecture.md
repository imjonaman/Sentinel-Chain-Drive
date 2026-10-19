# Phase 4: Deterministic Policy Engine Architecture

## 1. Overview and Core Philosophy

In Sentinel Chain Drive, Phase 3 (AgentID) establishes cryptographic agent identity, credential validation, replay prevention, and capability boundaries. Phase 4 introduces the **Deterministic Policy Engine**, an authoritative, stateless evaluation engine that evaluates financial transaction requests and produces exactly one of four explicit outcomes:

- `ALLOW`: All required security, capability, account, and institutional policy checks passed. Authorizes the transaction without settling it.
- `STEP_UP`: The transaction requires human supervisor signoff or dual-control approval before execution. Must not settle.
- `HOLD`: Potential risk, velocity anomaly, or uncertainty detected. Places the transaction into manual institutional review. Must not settle.
- `DECLINE`: Hard violation of security, credential, capability, account status, or policy limits. Rejects the transaction.

### Critical Safety Invariants:
1. **Deterministic Execution**: Given identical policy version, transaction intent, verified identity, capability state, and risk inputs, the engine will always produce the exact same decision trace.
2. **No LLM in the Loop**: Evaluation is strictly deterministic and rules-based. No non-deterministic models or language models participate in payment approvals.
3. **Fail-Closed Semantics**: If any credential, capability, account, or dependency is missing, invalid, or experiencing errors, the engine defaults to `DECLINE` (or `HOLD` for temporary dependencies), never `ALLOW`.
4. **Information Shielding**: Detailed internal rule mechanics and adversary-exploitable heuristics are shielded from external client responses, but fully preserved in tamper-evident internal audit evidence.
5. **Double-Spend Prevention via Spending Reservations**: An atomic pending-spend reservation mechanism prevents concurrent transactions from exceeding daily capability limits under high transaction throughput.

---

## 2. Evaluation Pipeline and Precedence Hierarchy

The policy evaluation pipeline follows an explicit, ordered sequence with unambiguous conflict resolution:

```
[Request Input]
       |
       v
1. Schema & Decimal Validation
       |
       v
2. Security & Credential Checks (AgentID, Ed25519 signature, Nonce, Skew, Status)
       |---> [Failed] ---> DECLINE (Priority 1)
       v
3. Account & Institution Status Checks (Active, Frozen, Closed)
       |---> [Failed] ---> DECLINE (Priority 2)
       v
4. Capability Envelope Checks (Single limit, 24h spend + reservations, Currencies, Beneficiary, Window)
       |---> [Failed] ---> DECLINE (Priority 3)
       v
5. Institutional Policy Limits & Blacklists
       |---> [Failed] ---> DECLINE (Priority 4)
       v
6. Risk & Velocity Triggers (Anomaly, High Risk Score)
       |---> [Triggered] ---> HOLD (Priority 5)
       v
7. Step-Up / Dual-Control Triggers (Amount threshold, Medium Risk Score)
       |---> [Triggered] ---> STEP_UP (Priority 6)
       v
8. Default Baseline Rule
       |---> [All Passed] ---> ALLOW (Priority 7)
```

### Precedence Rules:
- **Priority 1 (Hard Security Violations)**: Invalid signature, replayed nonce, expired/revoked credentials, inactive/revoked agent, or tampered intent immediately produces `DECLINE`. Can never be overridden by step-up or permissive rules.
- **Priority 2 (Account & Institution Restrictions)**: Inactive institution, frozen/closed origin or destination account immediately produces `DECLINE`.
- **Priority 3 (Capability Envelope Violations)**: Amount exceeding single limit, 24h cumulative spend breach, disallowed currency, unauthorized purpose, or out-of-operating-window immediately produces `DECLINE`.
- **Priority 4 (Institutional Policy Declines)**: Hard institutional limits (e.g. max cap per transaction) produce `DECLINE`.
- **Priority 5 (Hold Triggers)**: High risk score (e.g. >= 0.85), suspicious velocity spike, or manual review flag produces `HOLD`.
- **Priority 6 (Step-Up Triggers)**: Amount exceeding dual-control threshold (e.g. >= $10,000) or medium risk score (0.50 - 0.85) produces `STEP_UP`.
- **Priority 7 (Default Permissive Rule)**: All constraints passed -> `ALLOW`.

---

## 3. Data Models and State Governance

### A. Policy (`policies`)
- `id`: UUID (Primary Key)
- `institution_id`: UUID | None (Null denotes system-wide default baseline)
- `policy_code`: String(64) (e.g. `DEFAULT_BANKING_POLICY`)
- `version`: Integer (Monotonically increasing version number)
- `priority`: Integer (Precedence among active policies)
- `rules`: JSON (Configurable predicates and thresholds)
- `is_active`: Boolean
- `activated_at`: DateTime(UTC)
- `activated_by`: String(128)

### B. Policy Evaluation Record (`policy_evaluations`)
- `id`: UUID (Primary Key)
- `idempotency_key`: String(128) (Unique per institution/request)
- `institution_id`: UUID
- `agent_id`: UUID
- `transaction_id`: UUID | None
- `transaction_intent_hash`: String(64) (SHA-256 digest of canonical transaction fields)
- `policy_id`: UUID
- `policy_version`: Integer
- `decision`: "ALLOW" | "STEP_UP" | "HOLD" | "DECLINE"
- `reason_codes`: JSON (List of machine-readable reason codes)
- `applicable_rule_ids`: JSON (List of internal rule identifiers)
- `evaluation_evidence`: JSON (Diagnostic context, thresholds, risk inputs)
- `step_up_challenge_id`: UUID | None
- `hold_id`: UUID | None
- `spending_reservation_id`: UUID | None
- `evaluated_at`: DateTime(UTC)
- `correlation_id`: String(64) | None

### C. Step-Up Challenge (`step_up_challenges`)
- `id`: UUID
- `policy_evaluation_id`: UUID
- `transaction_intent_hash`: String(64)
- `policy_version`: Integer
- `initiating_agent_id`: UUID
- `institution_id`: UUID
- `verification_type`: String(64) (e.g. `SUPERVISOR_APPROVAL`)
- `required_role`: String(32) (e.g. `SUPERVISOR`)
- `status`: "PENDING" | "COMPLETED" | "REJECTED" | "EXPIRED"
- `expires_at`: DateTime(UTC)
- `approver_id`: String(128) | None
- `decision_reason`: String(500) | None

### D. Transaction Hold (`transaction_holds`)
- `id`: UUID
- `policy_evaluation_id`: UUID
- `transaction_intent_hash`: String(64)
- `institution_id`: UUID
- `hold_reason`: String(256)
- `review_workflow`: String(64)
- `status`: "ACTIVE" | "RELEASED" | "CONFIRMED_DECLINE"
- `resolved_by`: String(128) | None
- `resolution_notes`: String(500) | None

### E. Spending Reservation (`spending_reservations`)
- `id`: UUID
- `agent_id`: UUID
- `institution_id`: UUID
- `amount`: Numeric(18, 4)
- `currency`: String(3)
- `status`: "ACTIVE" | "FULFILLED" | "RELEASED" | "EXPIRED"
- `expires_at`: DateTime(UTC)

---

## 4. Concurrency and Spending Reservation Semantics

Under high-frequency execution, multiple agents or distributed instances could submit concurrent requests. To eliminate Time-of-Check to Time-of-Use (TOCTOU) race conditions:
1. The agent row is locked using `SELECT ... FOR UPDATE` (or database table locks on SQLite).
2. The effective 24-hour spend is calculated as:
   $$\text{Total Velocity} = \sum(\text{Committed Settled/Authorized Spend}) + \sum(\text{Active Spending Reservations})$$
3. If $\text{Total Velocity} + \text{Request Amount} > \text{Daily Limit}$, the request is declined immediately (`CAPABILITY_DAILY_LIMIT_EXCEEDED`).
4. If `ALLOW` or `STEP_UP`/`HOLD`, an active `SpendingReservation` is created atomically.
5. When a transaction reaches `SETTLED`, the reservation is fulfilled. If rejected or cancelled, it is released.

---

## 5. Idempotency and Intent Binding

- Requests include an `idempotency_key`.
- If an existing evaluation matches the `idempotency_key` and has an identical `transaction_intent_hash`, the recorded decision is returned idempotently.
- If the `idempotency_key` matches but the transaction intent is different (amount, currency, accounts, or purpose changed), the request is rejected with HTTP 409 Conflict (`IDEMPOTENCY_CONFLICT`).
