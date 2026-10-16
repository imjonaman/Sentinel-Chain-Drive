# AgentID and Capability Registry Architecture

## 1. Overview and Problem Statement

In an enterprise banking environment where autonomous AI agents initiate financial transfers, standard API keys or bearer tokens are insufficient. An AI agent with standing permissions can be compromised via prompt injection, model jailbreaks, or tool-misuse bugs, leading to unauthorized cross-bank payments.

**Sentinel Chain Drive Phase 3 introduces AgentID:**
1. **Cryptographic Identity:** Every agent is bound to a registered, versioned asymmetric public key (Ed25519).
2. **Cryptographic Intent Binding:** Financial requests must be explicitly signed by the agent's private key over a canonical representation of the transaction intent.
3. **Explicit Capability Envelopes:** Agents are constrained by hard single-transaction limits, 24-hour cumulative velocity caps, currency whitelists, beneficiary account whitelists, and operating time-of-day windows.
4. **Server-Side Enforcement & Nonce Protection:** Verification rejects expired timestamps, replayed nonces, revoked credentials, or inactive agent states before any transaction can proceed.

---

## 2. Threat Model and Security Boundaries

```
[Institutional Admin] ----(Registers Agent & Capabilities)----> [FastAPI Gateway]
                                                                        |
                                                                        v
[AI Agent Runtime (Holds Private Key)]                          [PostgreSQL Store]
        |                                                       - Public Keys
        |                                                       - Capabilities
   (Signs Intent)                                               - Nonce Store
        |                                                       - Audit Records
        v                                                               |
[Signed Credential / Intent] ----(Presents for Verification)------------+
```

### Threat Vectors and Mitigation Strategies:

| Threat Vector | Description | Mitigation Strategy |
|---|---|---|
| **Private Key Exposure** | Leakage of private signing keys via APIs or logs. | Private keys are held solely by the agent/KMS. APIs never accept or store private keys. Verification uses stored public keys. |
| **Credential Replay** | An adversary intercepts a valid signed credential and replays it. | Request nonces are enforced as unique in `processed_nonces`. Requests older than 300 seconds are rejected immediately. |
| **Tampered Intent** | An attacker alters the transaction amount, currency, or destination. | The signed claims contain a SHA-256 hash of canonical transaction attributes (`transaction_hash`). Any alteration invalidates the Ed25519 signature. |
| **Algorithm Substitution** | Attacker specifies a weak or "none" algorithm in the header. | Strict algorithm allowlist. Only `"Ed25519"` is supported and accepted; arbitrary algorithms are rejected. |
| **Privilege Escalation** | Agent attempts to modify its own capability envelope or limits. | Capabilities can only be provisioned through administrative endpoints with institution security context. |
| **Zombie Agent Execution** | Actions initiated by decommissioned or compromised agents. | Revocation is immediate and terminal (`REVOKED`). Suspended, expired, and pending agents fail verification closed. |
| **Cross-Tenant Impersonation** | Agent registered under Bank A attempts to authorize transfers for Bank B. | Sponsoring institution ID is cryptographically bound and validated against the requesting tenant context. |

---

## 3. Credential Structure and Canonical Serialization

### A. Claims Schema
The signed credential payload consists of a structured JSON dictionary:
```json
{
  "credential_id": "cred-7f3b8901-0000-0000-0000-000000000001",
  "agent_id": "11111111-0000-0000-0000-000000000001",
  "institution_id": "10000000-0000-0000-0000-000000000001",
  "issuer": "sentinel:authority:inst-1",
  "audience": "sentinel:gateway",
  "action_type": "TRANSFER",
  "nonce": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
  "timestamp": "2026-10-16T12:00:00Z",
  "expires_at": "2026-10-16T12:05:00Z",
  "key_version": 1,
  "transaction_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```

### B. Canonical Serialization Rule
To guarantee deterministic signature generation and verification across heterogeneous platforms:
1. JSON keys are sorted lexicographically.
2. Whitespace is stripped (`separators=(',', ':')`).
3. Encoding is strictly UTF-8.
4. Float values are prohibited; numeric bounds and amounts are formatted as strings.

### C. Signature Generation & Verification
- **Algorithm:** Ed25519 (RFC 8032) via PyCA `cryptography`.
- **Signature Encoding:** Hexadecimal or URL-safe Base64 string.
- **Verification Rule:** `public_key.verify(signature_bytes, canonical_payload_bytes)`.

---

## 4. Agent Lifecycle State Machine

```
              +---------------------+
              |  PENDING_APPROVAL   |
              +---------------------+
                 /               \
                /                 \ (Reject/Revoke)
               v                   v
        +------------+       +------------+
  +---> |   ACTIVE   | ----> |  REVOKED   | [TERMINAL]
  |     +------------+       +------------+
  |        |      |                ^
  |        v      v                |
  |  +-----------+  +-----------+  |
  +--| SUSPENDED |  |  EXPIRED  | -+
     +-----------+  +-----------+
```

### Legal Transitions:
- `PENDING_APPROVAL` &rarr; `ACTIVE`, `REVOKED`
- `ACTIVE` &rarr; `SUSPENDED`, `REVOKED`, `EXPIRED`
- `SUSPENDED` &rarr; `ACTIVE`, `REVOKED`, `EXPIRED`
- `EXPIRED` &rarr; `REVOKED`
- `REVOKED` &rarr; **Terminal (No transitions permitted).**

Reactivating a revoked agent is strictly prohibited. If an agent was decommissioned, a new registration workflow with a new keypair must be conducted.

---

## 5. Capability Envelope Enforcement

Every active agent is bound to a `Capability` record:
1. **Single Transaction Ceiling:** `amount <= max_single_transaction_amount`.
2. **24-Hour Cumulative Spend Limit:** Calculated dynamically by querying all authorized and settled transactions initiated by the agent within `[now - 24 hours, now]`:
   `current_24h_spend + amount <= max_daily_cumulative_amount`.
3. **Currency Whitelist:** `currency in allowed_currencies`.
4. **Purpose Whitelist:** `purpose_code in allowed_purpose_codes`.
5. **Destination Whitelist (Optional):** If `allowed_destination_accounts` is configured (non-null and non-empty), `destination_account_id` must match an approved beneficiary.
6. **Operating Time Window (Optional):** If `operating_window_start_utc` and `operating_window_end_utc` are defined, `current_utc_time` must fall within the window.

---

## 6. Auditability and Immutable Evidence

Every authorization attempt produces an immutable `AuthorizationRecord`:
- `decision`: `"AUTHORIZED"` or `"DECLINED"`.
- `reason_code`: e.g. `"CAPABILITY_EXCEEDED"`, `"SIGNATURE_INVALID"`, `"AGENT_REVOKED"`, `"NONCE_REPLAY"`, `"APPROVED"`.
- `signature_hash`: SHA-256 hash of the presented signature.
- `correlation_id`: Propagated from HTTP headers for end-to-end tracing.
- Atomic commit: Persisted within the same database transaction as the nonce recording.

---

## 7. Concurrency, Replay Protection & Database Integrity

### A. Pessimistic Row-Level Locking (`SELECT ... FOR UPDATE`)
To prevent Time-of-Check to Time-of-Use (TOCTOU) race conditions on cumulative spending limits:
- The verification pipeline locks the `Agent` row (`select(Agent).where(Agent.id == req.agent_id).with_for_update()`).
- In PostgreSQL (under Read Committed isolation level), concurrent authorization requests for the same agent are serialized.
- When an initial transaction completes and commits its `AuthorizationRecord`, subsequent transactions acquire the lock and re-evaluate `get_24h_spend_sum()` against the committed state, preventing double-spend ceiling breaches.
- Spending velocity is strictly partitioned by currency (`where AuthorizationRecord.currency == req.transaction.currency`), preventing currency-mixing errors across international accounts.

### B. High-Entropy Replay Nonce Tracking
- Nonces are persisted to `processed_nonces` with a unique database constraint (`uq_processed_nonces_nonce`).
- Request timestamps are enforced within `|now - ts| <= 300` seconds tolerance.
- Nonce consumption and `AuthorizationRecord` persistence are committed atomically.
- Submissions attempting to reuse a consumed nonce fail closed with `REPLAY_DETECTED_NONCE_REUSED`.

---

## 8. Trust Boundaries: Simulation vs Production Controls

| Domain | Simulated Development Boundary | Production Target Implementation |
|---|---|---|
| **Tenant Authentication** | `X-Institution-ID` header matched against URL path and DB records. Returns 403 Forbidden on mismatch. | Mutual TLS (mTLS) with institutional X.509 certificates and JWT/OAuth2 bearer tokens. |
| **Agent Key Custody** | Asymmetric Ed25519 public keys stored in PostgreSQL; agent private key held in memory/test runner. | Bank HSM/KMS (PKCS#11 / AWS CloudHSM / GCP Cloud KMS) with non-exportable hardware keys. |
| **Database Concurrency** | SQLite file lock in unit tests; PostgreSQL row-level `FOR UPDATE` in deployment. | PostgreSQL transactional pooler (Session mode) with explicit row-level locks on `agents`. |
| **Audit Logs** | Append-only database records in `audit_logs` and `authorization_records`. | Write-Once-Read-Many (WORM) storage, permissioned DRUNIX distributed ledger blocks. |
