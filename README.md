# Sentinel Chain Drive

**AI-Agent Authorization and Cross-Bank Fraud Intelligence Platform**

Sentinel Chain Drive is an enterprise security and intelligence platform designed to govern autonomous AI-agent financial transactions and detect cross-institution fraud networks. The platform couples deterministic policy evaluation and AI capability bounds with privacy-preserving cross-bank transaction graph analytics.

---

## Current Status: Phase 6 Complete (Audited: 2026-10-19)

Sentinel Chain Drive is developed under an explicit 13-phase architectural roadmap defined in [`build_order.txt`](file:///c:/Users/imjon/OneDrive/Documents/GitHub/Sentinel-Chain-Drive/build_order.txt). As of the latest repository audit on **2026-10-19**, **Phases 1 through 6 are COMPLETE and VERIFIED**, with 187 automated unit and integration tests passing.

### Master Phase Status Summary

| Phase | Title | Status | Summary / Scope |
| :---: | :--- | :---: | :--- |
| **1** | **Foundation and Development Environment** | **COMPLETE** | Enterprise FastAPI framework, structured logging, correlation IDs, error taxonomy, async database engine, Alembic baseline. |
| **2** | **Simulated Banking Environment & Transaction Domain** | **COMPLETE** | Multi-institution domain, account management with lifecycle bounds, decimal-safe transaction state machine, idempotency, synthetic seeds. |
| **3** | **AgentID - AI-Agent Identity & Capability Authorization** | **COMPLETE** | Ed25519 cryptographic signatures, canonical transaction intent hashing, capability limits, single-use nonces, terminal revocation. |
| **4** | **Deterministic Policy Engine** | **COMPLETE** | 7-tier precedence evaluation producing `ALLOW`, `STEP_UP`, `HOLD`, or `DECLINE`, spending reservations for concurrency, dual-control, policy versioning. |
| **5** | **MuleChain - Graph-Based Fraud Intelligence** | **COMPLETE** | In-memory NetworkX directed multigraph (`MultiDiGraph`), 4 topological detectors (fan-in, fan-out, rapid pass-through, circular layering), explainable 0–100 risk scoring, idempotent SHA-256 fingerprint deduplication, Phase 4 Policy Engine bridge. |
| **6** | **Privacy Gateway & Cross-Institution Intelligence** | **COMPLETE** | Keyed HMAC-SHA256 pseudonymization (`MeshID`) with purpose-binding and epoch rotation, field-level disclosure policies & prohibited-field rejection, shared indicator registry, anti-enumeration rate limiting, policy engine risk bridge. |
| **7** | **DRUNIX Ledger Integration** | **PARTIALLY COMPLETE** | Abstract `DRUNIXAdapter` and in-memory `MockDRUNIXAdapter` verified; live RPC adapter, mTLS, and ledger submission queue remain unbuilt. |
| **8** | **Event Processing & System Coordination** | **NOT STARTED** | Transactional Outbox pattern, RabbitMQ topic exchange topology, dead-letter queues, idempotent event consumers. |
| **9** | **Investigation, Case Management, & Recovery Orchestration** | **NOT STARTED** | Alert triage API, fraud case management, evidentiary audit dossier compiler, simulated recovery orchestration. |
| **10** | **Frontend Dashboard & Operator Experience** | **NOT STARTED** | React 18/19, TypeScript, Vite SPA, interactive Cytoscape.js transaction graph visualization, operator queues, policy console. |
| **11** | **Security Hardening & Adversarial Validation** | **NOT STARTED** | Standalone adversarial attack test harness, chaos fault injection (database/broker disconnects), automated container scanning. |
| **12** | **Controlled Pilot Readiness** | **NOT STARTED** | Pilot integration specifications (ISO 20022), disaster recovery runbooks (PITR drills), institutional KMS guides. |
| **13** | **Production Deployment & Multi-Institution Scale** | **NOT STARTED** | Helm charts, Kubernetes HPA, OpenTelemetry distributed tracing, Prometheus metrics export, SIEM log forwarding, database RLS. |

*Detailed audit evidence, verification logs, and acceptance criteria are documented in [`docs/phase_status_audit.md`](file:///c:/Users/imjon/OneDrive/Documents/GitHub/Sentinel-Chain-Drive/docs/phase_status_audit.md).*

---

## Implemented Architectural Capabilities (Phases 1–6)

### Phase 1: Foundation & Core Infrastructure
- **Enterprise Web Framework:** FastAPI running on Starlette with asynchronous request handling.
- **Structured JSON Logging:** Contextual logging using `contextvars` to bind `X-Correlation-ID` across all log records.
- **Sensitive Data Redaction:** Automatic regex-based masking in structured logs for passwords, secrets, private keys, and tokens.
- **Defense-in-Depth Middleware:**
  - `SecurityHeadersMiddleware`: Outbound HTTP security headers (`nosniff`, `DENY`, strict referrer, CSP).
  - `RequestSizeLimitMiddleware`: Rejection of inbound payloads exceeding 1 MB with `HTTP 413`.
- **Database Architecture:** SQLAlchemy 2.x asynchronous engine with connection pooling, pre-ping verification, and transaction context management.
- **Schema Migrations:** Alembic async migration harness with immutable audit log baseline.
- **Health Probes:** Liveness (`/health/live`) and database-backed readiness (`/health/ready`) probes.

### Phase 2: Banking Domain & Transaction Lifecycle
- **Multi-Institution Management:** Institutional registry (`ACTIVE`, `SUSPENDED`, `INACTIVE`) with SWIFT/BIC-compliant routing identifiers and strict lifecycle transitions.
- **Synthetic Account Management:** Checking, savings, operational, and settlement accounts with non-negative balance constraints (`Numeric(18, 4)`) and lifecycle states (`ACTIVE`, `FROZEN`, `CLOSED`).
- **Strict Monetary Precision:** Fixed-scale `Decimal` representation across all financial calculations; binary floating-point math is strictly forbidden.
- **Transaction State Machine:** Enforced state progression:
  `SUBMITTED` &rarr; `PENDING_AUTHORIZATION` &rarr; `AUTHORIZED` &rarr; `SETTLED` | `REJECTED` | `CANCELLED` (or `HELD`).
- **Deterministic Idempotency:** Unique database constraints on `idempotency_key`. Replays of identical payloads return existing resources (`HTTP 200 OK`); conflicting reuse returns `HTTP 409 Conflict`.
- **Atomic Audit Trail:** Every status change is captured in `transaction_status_history` with actor, reason, timestamp, and correlation ID.
- **Synthetic Seed Generator:** Deterministic, reproducible test fixtures provisioning 4 institutions, 7 accounts, and 4 lifecycle-exercising transactions with zero customer PII.

### Phase 3: AgentID Cryptographic Authorization
- **Cryptographic Identity:** Registered AI agents bound to versioned Ed25519 public keys with support for key rotation (`POST /agents/{id}/rotate-key`).
- **Deterministic Intent Binding:** SHA-256 digest of canonical transaction attributes (`transaction_intent_hash`). Payloads are serialized lexicographically with stripped whitespace and float prohibition.
- **Capability Envelopes:** Enforced upper bounds on:
  - Single transaction maximum amount (`max_amount_per_transaction`).
  - 24-hour cumulative spending limit (`max_daily_cumulative_amount`).
  - Permitted currency whitelist (e.g. `['USD']`) with multi-currency velocity isolation.
  - Whitelisted origin and destination accounts.
  - UTC operating hour windows (`operating_start_hour_utc` to `operating_end_hour_utc`).
- **Replay & Clock Skew Protection:** Single-use nonce tracking in database (`processed_nonces`) and strict timestamp validity checking (`|now - timestamp| <= 300s`).
- **Terminal Revocation:** Agent lifecycle state machine (`PENDING_APPROVAL`, `ACTIVE`, `SUSPENDED`, `REVOKED`, `EXPIRED`), where `REVOKED` is non-reversible.

### Phase 4: Deterministic Policy Engine
- **Four Canonical Outcomes:** Every transaction evaluation produces exactly one deterministic outcome:
  - `ALLOW`: Authorizes the transaction (does not auto-settle).
  - `STEP_UP`: Halts execution pending human supervisor review; generates an immutable challenge bound to intent hash and policy version.
  - `HOLD`: Places transaction into institutional review queue due to suspicious risk score or velocity anomaly.
  - `DECLINE`: Fails closed upon security violation, limit breach, or frozen account with stable reason codes.
- **7-Tier Rule Precedence Hierarchy:**
  1. *Priority 1 (Security Violations):* Invalid signature, revoked agent, replayed nonce, or clock skew &rarr; Immediate `DECLINE`.
  2. *Priority 2 (Account Restrictions):* Origin or destination account `FROZEN` or `CLOSED` &rarr; Immediate `DECLINE`.
  3. *Priority 3 (Capability Limits):* Single limit exceeded or 24h spend breach &rarr; Immediate `DECLINE`.
  4. *Priority 4 (Institutional Limits):* Hard institution maximum cap exceeded &rarr; Immediate `DECLINE`.
  5. *Priority 5 (Fraud & Risk Holds):* Risk score >= hold threshold or velocity anomaly &rarr; `HOLD`.
  6. *Priority 6 (Step-Up Dual Control):* Amount >= step-up threshold or elevated risk score &rarr; `STEP_UP`.
  7. *Priority 7 (Default Rule):* All checks passed &rarr; `ALLOW`.
- **Atomic Spending Reservations:** Parallel transactions competing for remaining 24-hour velocity are serialized via row locks (`SELECT ... FOR UPDATE` on Agent) and tracked in `spending_reservations`, preventing concurrent double-spending.
- **Separation of Duties:** Step-up challenges strictly prohibit the initiating agent from approving its own transaction (`HTTP 403 Forbidden`).
- **Information Shielding:** Public evaluation endpoints shield internal rule IDs and evidence, returning only high-level reason codes. Authorized fraud investigators access granular traces via `/api/v1/policies/evaluations/{id}/detail`.
- **Policy Versioning & Auditing:** Monotonically increasing policy versions with explicit activation tracking (`activated_by`, `activated_at`). Every evaluation atomically persists an immutable `policy_evaluations` audit record.

### Phase 5: MuleChain Graph Fraud Intelligence Engine
- **NetworkX Directed Multigraph (`MultiDiGraph`):** In-memory topological graph representation capturing account nodes and parallel directed transaction edges with timestamps, amounts, currencies, and purpose codes.
- **Strict Invariants:**
  - *Exact Currency Isolation:* Analysis operates strictly per single currency. Cross-currency amounts are never aggregated without explicit conversion.
  - *Settlement Invariant:* Only `SETTLED` transactions represent completed fund flows. Rejected, submitted, or cancelled transactions are excluded from flow graphs.
  - *Cutoff Bounds & Determinism:* Time-bounded sliding windows and deterministic node/edge ordering ensure reproducible graph construction.
- **Topological Pattern Detectors:**
  1. *Fan-In Smurfing (`FanInDetector`):* Identifies $N \ge 3$ distinct source accounts transferring funds into a common destination account within a configurable time window (default 3600s), with subset burst deduplication.
  2. *Fan-Out Dispersal (`FanOutDetector`):* Identifies a source account distributing funds across $N \ge 3$ distinct destination accounts within a configurable window (default 3600s).
  3. *Rapid Pass-Through (`RapidPassThroughDetector`):* Detects transit mule behavior where ingress funds are rapidly dispersed onward (delta $\le$ 1800s) with high retention ratio ($\ge$ 80%).
  4. *Circular Layering (`CircularLayeringDetector`):* Identifies directed cycles from 2 up to $K \le 5$ hops within time-bounded windows (default 7200s), with cycle bounds preventing combinatorial explosion.
- **Explainable Risk Scoring (0–100 Scale):** Deterministic multi-indicator scoring mapped to explicit severity tiers (`LOW` < 40, `MEDIUM` 40–69, `HIGH` 70–84, `CRITICAL` $\ge$ 85). Retains granular evidence: accounts, transactions, timestamps, amounts, rule versions, and scoring rationale.
- **Idempotent Alert Persistence:** SHA-256 fingerprinting over `(institution_id, detector_type, primary_account_id, currency, transaction_ids, rule_version)` guarantees repeated analysis over identical snapshots produces zero duplicate alerts.
- **Phase 4 Policy Engine Bridge:** Converts MuleChain findings into structured `RiskSignals` telemetry (`risk_score`, `velocity_warning`, `manual_review_flag`) consumed by the deterministic policy engine to trigger `HOLD` or `STEP_UP`.

### Phase 6: Privacy Gateway and Cross-Institution Intelligence
- **Purpose-Bound HMAC-SHA256 Pseudonyms (`MeshID`):** Keyed cryptographic pseudonymization (`MeshID = HMAC-SHA256(SecretKey_Epoch, Purpose || ":" || InstitutionCode || ":" || AccountNumber)`). Normalized whitespace, uppercase institution codes, canonical string representations, float/unkeyed hash prohibition, and versioned epoch rotation (`epoch_2026_q4`) preventing dictionary/rainbow-table attacks and cross-purpose correlation.
- **Field-Level Disclosure Policies & Prohibited-Field Rejection:** Strict allowlist filtering proactively rejecting direct PII and accounts (`raw_account_number`, `customer_name`, `private_key`, `credentials`, `transaction_ids`, `balance`). Coarse volume tiers (`TIER_MICRO_UNDER_1K` through `TIER_HIGH_OVER_100K`) preserve topological utility without leaking exact balances.
- **Shared Indicator Exchange Data Model (`SharedIndicator`):** Versioned, idempotent intelligence schema persisted in PostgreSQL with unique constraint `uq_shared_indicators_origin_mesh_type_policy` preventing duplicate publications. Supports origin confidence [0.0, 1.0], pattern categories, sanitized evidence summaries, and explicit withdrawal/revocation.
- **Anti-Enumeration & Scoped Query Controls:** Wildcard or bulk scraping of pseudonyms is strictly denied. Queries require an explicit target `MeshID` and authorized purpose; queries are bounded and sliding-window rate limited per institution via `PrivacyQueryRateLimiter`.
- **Phase 4 Policy Engine Integration Bridge:** Translates active cross-institution indicators into deterministic `RiskSignals` telemetry (0.90 + review flag for `CRITICAL`, 0.75 for `HIGH`, explicit `NO_MATCH` for clean accounts, explicit `UNAVAILABLE` fallback for gateway outages) driving deterministic `HOLD`/`STEP_UP` without weakening policy engine authority.
- **Atomic Privacy Audit Logging (`PrivacyAuditLog`):** Transactionally records publication, query, revocation, withdrawal, and rejected unauthorized attempts with sensitive data redaction.

---

## Technology Stack

- **Language & Runtime:** Python 3.13+ (Targeting 3.13 / 3.14)
- **Web Framework:** FastAPI (>= 0.115.0) on Starlette (>= 1.8.0)
- **Graph Analytics:** NetworkX (>= 3.4.0)
- **Data Validation & Settings:** Pydantic v2 (>= 2.10.0), Pydantic Settings (>= 2.7.0)
- **Cryptography & Signatures:** PyCA `cryptography` (>= 43.0.0, Ed25519 signing/verification, RFC 8032; HMAC-SHA256)
- **ORM & Persistence:** SQLAlchemy 2.x (>= 2.0.36) with Greenlet, asyncpg (>= 0.30.0) for operational FastAPI queries, psycopg[binary] (>= 3.2.0) for Alembic DDL migrations
- **Database Migrations:** Alembic (>= 1.14.0)
- **Testing Harness:** pytest (>= 8.3.0), pytest-asyncio (>= 0.24.0), HTTPX (>= 0.28.0), aiosqlite (>= 0.20.0)
- **Code Quality & Static Analysis:** Ruff (>= 0.8.0), mypy (>= 1.13.0, strict mode)
- **Containerization:** Docker & Docker Compose (PostgreSQL 16)

---

## Architecture & Trust Boundaries

```
[External AI Agent]                          [Institutional Supervisor]
       | (Signs Intent with Ed25519)                      | (Dual-Control Step-Up)
       v                                                  v
[FastAPI Gateway] <--(X-Institution-ID Tenant Context)----+
       |
       +---> [AgentID Verification Engine]
       |     - Ed25519 Signature Verification
       |     - Nonce Replay Check (processed_nonces)
       |     - Clock Skew Validation (|now - ts| <= 300s)
       |     - Capability Envelope Boundary Validation
       |
       +---> [Deterministic Policy Engine] <---+ [Privacy Gateway Bridge]
       |     - 7-Tier Precedence Hierarchy     | (Consumes MeshID Signals)
       |     - Row-Locked Agent Serialization  |
       |     - Spending Reservations           |
       |     - Outcomes: ALLOW/STEP_UP/HOLD    |
       |                                       |
       +---> [Privacy Gateway Service] --------+
       |     - Purpose-Bound MeshID (HMAC-SHA256)
       |     - Field-Level Disclosure Allowlist & Redaction
       |     - Anti-Enumeration Sliding-Window Rate Limiting
       |     - Shared Indicator Publication & Query Scoping
       |     - Privacy Audit Log Persistence
       |
       +---> [MuleChain Graph Engine]
       |     - In-Memory NetworkX MultiDiGraph
       |     - Topological Anomaly Detectors
       |     - Idempotent Alert Persistence (fraud_alerts)
       |
       +---> [Operational PostgreSQL Datastore]
       |     - Authoritative State (Institutions, Accounts, Tx, Policies)
       |     - Fraud Alerts & Shared Indicators
       |     - Atomic Audit Log & Privacy Audit Trails
       |
       +---> [DRUNIX Adapter (Off-Chain Boundary)]
             - MockDRUNIXAdapter (In-memory development contract)
```

### Critical Trust Boundaries:
1. **Local Real-Time Authorization vs. Asynchronous Fraud Analysis:** Real-time transaction authorization (evaluating AgentID credentials, account flags, and capability limits) executes strictly on the synchronous path. Graph analysis (MuleChain, Phase 5) and ledger commitments (DRUNIX, Phase 7) operate asynchronously to prevent network/ledger latency from stalling payment execution.
2. **Development Simulation Boundary:** HTTP headers like `X-Institution-ID` and simulated roles are development scaffolding to test tenant boundaries in local simulation. They **do not** constitute production-grade identity assurance or authentication (which requires mutual TLS / OIDC in enterprise deployment).
3. **Information Shielding & Privacy Preservation:** Public evaluation responses return coarse reason codes to avoid exposing internal security rules. Cross-institution intelligence is strictly sanitized: raw customer names, account numbers, credentials, and full transaction histories are prohibited and rejected. Pseudonyms are purpose-bound and epoch-rotated; bulk scraping is denied.
4. **Authoritative Datastore:** PostgreSQL is the sole authoritative operational store. External distributed ledgers (DRUNIX) serve solely for immutable state attestation and cross-bank proofs.

---

## How to Run

Follow either of the two execution workflows below to run Sentinel Chain Drive:

### Prerequisites
- **Python:** Version 3.13 or newer
- **Docker & Docker Compose:** For running the PostgreSQL 16 database or the full containerized stack
- **Git:** For repository cloning and branch management

---

### Option 1: Running Locally (Python Virtual Environment)

#### 1. Clone Repository & Setup Virtual Environment
```powershell
# Clone the repository
git clone https://github.com/imjonaman/Sentinel-Chain-Drive.git
cd Sentinel-Chain-Drive

# Create and activate virtual environment (Windows PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# (Linux / macOS alternative)
# python3 -m venv .venv
# source .venv/bin/activate
```

#### 2. Install Project and Dependencies
```powershell
pip install -e ".[dev]"
```

#### 3. Start PostgreSQL Database
Start the PostgreSQL container via Docker Compose:
```powershell
docker-compose up -d db
```
*Wait ~5 seconds for the database healthcheck to report healthy.*

#### 4. Apply Database Migrations
Run Alembic migrations to apply all schema versions up to head:
```powershell
alembic upgrade head
```

#### 5. Seed Synthetic Demonstration Data (Optional)
Populate the database with deterministic institutions, accounts, and transactions:
```powershell
python -m sentinel_chain_drive.db.seed
```

#### 6. Start the FastAPI Application
Run the application with Uvicorn live-reloading:
```powershell
uvicorn sentinel_chain_drive.api.main:app --reload --host 0.0.0.0 --port 8000
```
The API is now running at `http://localhost:8000`.

---

### Option 2: Running with Docker Compose (Full Stack)

To run the complete platform (PostgreSQL database and FastAPI application container):

#### 1. Build and Launch Containers
```powershell
docker-compose up --build -d
```

#### 2. Run Database Migrations in Container
```powershell
docker-compose exec api alembic upgrade head
```

#### 3. Seed Synthetic Data in Container
```powershell
docker-compose exec api python -m sentinel_chain_drive.db.seed
```

#### 4. Inspect Container Logs
```powershell
docker-compose logs -f api
```

#### 5. Stop Containers
```powershell
docker-compose down
```

---

## Verifying the Running Application

### 1. Health & Readiness Probes
Confirm the service is running and connected to PostgreSQL:
```powershell
# Liveness probe
curl http://localhost:8000/health/live

# Readiness probe (verifies database connectivity)
curl http://localhost:8000/health/ready
```

### 2. Interactive API Documentation
Once running, open your web browser:
- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON Schema:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## Example API Usage

### 1. List Seeded Institutions
```bash
curl -X GET "http://localhost:8000/api/v1/institutions" \
  -H "Accept: application/json"
```

### 2. Submit a Simulated Transaction
```bash
curl -X POST "http://localhost:8000/api/v1/transactions" \
  -H "Content-Type: application/json" \
  -d '{
    "idempotency_key": "tx-demo-unique-key-001",
    "origin_institution_id": "00000000-0000-0000-0000-000000000001",
    "origin_account_id": "00000000-0000-0000-0000-000000000010",
    "destination_institution_id": "00000000-0000-0000-0000-000000000002",
    "destination_account_id": "00000000-0000-0000-0000-000000000020",
    "amount": "2500.0000",
    "currency": "USD",
    "transaction_type": "TRANSFER",
    "purpose_code": "INVOICE_PAYMENT"
  }'
```
*Response: `HTTP 201 Created` with status `PENDING_AUTHORIZATION`.*

### 3. Re-send Exact Same Request (Idempotency Test)
Re-submitting the exact same payload returns:
*Response: `HTTP 200 OK` with the existing transaction without creating a duplicate.*

### 4. Trigger MuleChain Graph Fraud Analysis
Analyze transaction graphs for topological smurfing, pass-through mules, and layering:
```bash
curl -X POST "http://localhost:8000/api/v1/mulechain/analyze" \
  -H "X-Institution-ID: 00000000-0000-0000-0000-000000000001" \
  -H "Content-Type: application/json" \
  -d '{
    "currency": "USD",
    "max_transactions": 1000
  }'
```
*Response: `HTTP 200 OK` with summary containing `alerts_generated`, `alerts_deduplicated`, and `detector_breakdown`.*

### 5. Publish Sanitized Indicator via Privacy Gateway
Share a privacy-preserving threat indicator using an epoch-keyed, purpose-bound MeshID:
```bash
curl -X POST "http://localhost:8000/api/v1/privacy-gateway/indicators/publish" \
  -H "X-Institution-ID: 00000000-0000-0000-0000-000000000001" \
  -H "Content-Type: application/json" \
  -d '{
    "pseudonymous_mesh_id": "a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0",
    "indicator_type": "MULE_RAPID_PASSTHROUGH",
    "severity": "CRITICAL",
    "confidence_score": 0.95,
    "pattern_category": "RAPID_DISPERSAL",
    "evidence_summary": {
      "pattern_type": "RAPID_DRAIN",
      "anonymized_volume_tier": "TIER_HIGH_100K_TO_1M",
      "mulechain_rule_version": "v1.0"
    },
    "provenance": {
      "source": "MULECHAIN_TOPOLOGY_DETECTOR"
    },
    "validity_hours": 72,
    "sharing_policy_version": "v1.0"
  }'
```
*Response: `HTTP 201 Created` with unique `indicator_code` (e.g. `IND-20261019-XXXX`) and stamped verified origin.*

### 6. Query Intelligence by MeshID (Anti-Enumeration Rate Limited)
Query active, unexpired indicators matching a known 64-hex MeshID:
```bash
curl -X POST "http://localhost:8000/api/v1/privacy-gateway/indicators/query" \
  -H "X-Institution-ID: 00000000-0000-0000-0000-000000000002" \
  -H "Content-Type: application/json" \
  -d '{
    "pseudonymous_mesh_id": "a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0",
    "purpose": "PAYMENT_AUTHORIZATION",
    "limit": 10
  }'
```
*Response: `HTTP 200 OK` with matching authorized indicators and remaining rate limit quota.*

---

## API Endpoints Reference

### Health & Monitoring
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health/live` | Liveness health probe |
| `GET` | `/health/ready` | Readiness probe (database connectivity check) |
| `GET` | `/api/v1/system/info` | System metadata (environment, version) |

### Institutions (`/api/v1/institutions`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/institutions` | Register a new financial institution |
| `GET` | `/api/v1/institutions` | List institutions with pagination and status filter |
| `GET` | `/api/v1/institutions/{id}` | Retrieve institution details by UUID |
| `PATCH` | `/api/v1/institutions/{id}` | Update institution metadata / settings |
| `PATCH` | `/api/v1/institutions/{id}/status` | Transition institution status (`ACTIVE`, `SUSPENDED`, `INACTIVE`) |

### Accounts (`/api/v1/accounts`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/accounts` | Create synthetic account under an institution |
| `GET` | `/api/v1/accounts` | List accounts (filterable by institution, currency, status) |
| `GET` | `/api/v1/accounts/{id}` | Retrieve account details by UUID |
| `PATCH` | `/api/v1/accounts/{id}/status` | Transition account status (`ACTIVE`, `FROZEN`, `CLOSED`) |

### Transactions (`/api/v1/transactions`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/transactions` | Submit transaction (idempotent, enters `PENDING_AUTHORIZATION`) |
| `GET` | `/api/v1/transactions` | List transactions with institution, status, and date filters |
| `GET` | `/api/v1/transactions/{id}` | Retrieve transaction and audit history |
| `POST` | `/api/v1/transactions/{id}/simulate-action` | Controlled simulation operations (`HOLD`, `REJECT`, `CANCEL`, `SETTLE`) |

### Agents & Capabilities (`/api/v1/institutions/{id}/agents`, `/capabilities`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/institutions/{id}/agents` | Register a new autonomous AI agent with Ed25519 public key |
| `GET` | `/api/v1/institutions/{id}/agents/{agent_id}` | Retrieve registered agent details |
| `POST` | `/api/v1/institutions/{id}/agents/{agent_id}/status` | Transition agent lifecycle status (`ACTIVE`, `SUSPENDED`, `REVOKED`) |
| `POST` | `/api/v1/institutions/{id}/agents/{agent_id}/rotate-key` | Rotate Ed25519 public key and increment key version |
| `POST` | `/api/v1/institutions/{id}/capabilities` | Assign capability envelope (limits, currencies, whitelist, operating window) |
| `GET` | `/api/v1/institutions/{id}/capabilities/{cap_id}` | Retrieve capability envelope |
| `POST` | `/api/v1/institutions/{id}/credentials` | Issue signed agent transaction credential |
| `POST` | `/api/v1/institutions/{id}/credentials/{cred_id}/revoke` | Revoke issued credential |
| `POST` | `/api/v1/credentials/verify` | Verify credential signature, intent hash, nonces, and capability limits |

### Policy Engine & Governance (`/api/v1/policies`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/policies/evaluate` | Deterministic transaction authorization evaluation (`ALLOW`, `STEP_UP`, `HOLD`, `DECLINE`) |
| `GET` | `/api/v1/policies/evaluations/{id}` | Retrieve public evaluation decision and reason codes |
| `GET` | `/api/v1/policies/evaluations/{id}/detail` | Retrieve full evaluation trace and evidence for authorized fraud investigators |
| `POST` | `/api/v1/policies/step-up/{challenge_id}/complete` | Submit dual-control step-up review decision (enforces separation of duties) |
| `POST` | `/api/v1/policies/holds/{hold_id}/resolve` | Resolve compliance/fraud hold (`RELEASE` to allow reevaluation or `CONFIRM_DECLINE`) |
| `POST` | `/api/v1/policies` | Create a new versioned institutional or global policy |
| `GET` | `/api/v1/policies` | List active and historical policies with filtering |
| `GET` | `/api/v1/policies/{id}` | Retrieve policy details and rule definitions |
| `PATCH` | `/api/v1/policies/{id}/status` | Activate or deactivate specific policy version |

### MuleChain Fraud Intelligence (`/api/v1/mulechain`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/mulechain/analyze` | Execute deterministic graph fraud analysis across synthetic transaction history |
| `GET` | `/api/v1/mulechain/alerts/{id}` | Retrieve specific fraud alert with full evidence payload (scoped by institution) |
| `GET` | `/api/v1/mulechain/alerts` | List detected fraud alerts with pagination, detector, severity, and status filters |

### Privacy Gateway & Cross-Institution Intelligence (`/api/v1/privacy-gateway`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/privacy-gateway/indicators/publish` | Publish pre-sanitized shared fraud indicator with HMAC-SHA256 MeshID |
| `POST` | `/api/v1/privacy-gateway/indicators/publish-from-alert` | Sanitize and publish an indicator directly from a MuleChain fraud alert |
| `POST` | `/api/v1/privacy-gateway/indicators/query` | Query active indicators for a specific MeshID (rate limited, no bulk scraping) |
| `GET` | `/api/v1/privacy-gateway/indicators/{id}` | Retrieve indicator details (scoped by originator, target, or broadcast) |
| `POST` | `/api/v1/privacy-gateway/indicators/{id}/revoke` | Revoke or withdraw a published indicator (restricted to originator) |
| `GET` | `/api/v1/privacy-gateway/audit-summary` | Retrieve privacy compliance audit summary statistics for caller institution |

---

## Verification & Testing

### Running Tests
Execute the automated test suite with pytest:
```powershell
pytest
```
*Current Result: **187 passed / 187 tests (100%)** in ~32s across unit and integration suites:*
- **Phase 1 Foundation:** 17 tests (configuration, correlation logging, health probes, errors)
- **Phase 2 Banking Domain:** 23 tests (institutions, accounts, transactions, decimal safety, idempotency)
- **Phase 3 AgentID:** 35 tests (Ed25519 signing, intent tampering, replay, clock skew, capabilities)
- **Phase 4 Policy Engine:** 38 tests (4 outcomes, precedence rules, spending reservations, step-up, holds, live concurrency)
- **Phase 5 MuleChain:** 31 tests (graph construction, currency isolation, status filtering, 4 detectors, explainable scoring, idempotent alerts, multi-tenant scoping, policy engine integration)
- **Phase 6 Privacy Gateway:** 43 tests (purpose-bound MeshID, canonicalization, epoch rotation, dual recursive allowlists, case variant detection, rate limiting, recipient scoping, revocation integrity, policy bridge)

### Code Quality & Static Analysis
```powershell
# Check code formatting (Ruff)
ruff format --check .

# Run linter checks (Ruff)
ruff check .

# Run strict static type verification (mypy)
mypy src tests

# Verify migration SQL generation (Alembic)
alembic upgrade --sql 20261019_0005:20261019_0006
```

---

## Security Invariants & Limitations

1. **Simulated Environment:** All accounts, routing numbers, and balances are strictly synthetic. No real-world banking networks (Fedwire, SWIFT, ACH) or customer credentials are used.
2. **Deterministic Financial Math:** Amounts are stored as exact scale decimals (`Numeric(18, 4)`) and serialized as string representations to avoid floating-point loss in JSON.
3. **No Premature Settlement:** Submissions enter `PENDING_AUTHORIZATION`. The policy engine produces `ALLOW`, `STEP_UP`, `HOLD`, or `DECLINE`. Authorization allows transaction settlement to proceed, but does not settle or execute funds directly.
4. **Development Authentication Boundary:** `X-Institution-ID` headers are simulation test fixtures and must not be treated as production identity tokens. Production deployment will require mutual TLS (mTLS) and OIDC integration.
5. **No Live Blockchain Ledger:** The `MockDRUNIXAdapter` operates entirely in memory to decouple Phase 1–6 local development from unverified distributed ledger dependencies.
6. **Concurrency Double-Spend Protection:** Pending transactions are protected by atomic `spending_reservations` records and database row locks, ensuring concurrent authorizations cannot exceed 24-hour capability bounds.
7. **Graph Scalability & In-Memory Constraints:** MuleChain currently runs NetworkX in-memory for deterministic localized graph analysis. Distributed graph databases (e.g. Neo4j) or message brokers (RabbitMQ) will be introduced in subsequent phases as specified in `build_order.txt`.
8. **Cross-Institution Privacy Preservation:** Keyed HMAC-SHA256 pseudonymization (`MeshID`) with purpose-scoping and epoch rotation prevents rainbow-table inversion and cross-purpose correlation. Outbound intelligence enforces dual recursive allowlists, coarse volume tiers, and automatic PII/account number redaction. Bulk scraping is strictly forbidden.
9. **Revocation Integrity & Immutability:** Revoked indicators cannot be silently resurrected under duplicate publication (`HTTP 409 Conflict`). Modifying findings for a revoked indicator requires explicitly advancing the `sharing_policy_version`.
10. **Fail-Closed Key Lifecycle:** Missing or unknown epoch keys fail closed immediately with `KeyError` without unsafe random fallback key generation.
11. **Production-Readiness Boundary:** While development exit criteria for Phases 1–6 are 100% satisfied, this system is a development prototype and is **not** currently certified for production financial workloads (pending distributed messaging, Kubernetes orchestration, and formal security audits in Phases 8–13).

---

## Next Recommended Phase

**Phase 7: DRUNIX Ledger Integration**
- **Prerequisites Status:** Fully satisfied. Phase 1 provides the abstract `DRUNIXAdapter` interface and `MockDRUNIXAdapter` contract; Phase 6 provides sanitized privacy gateway indicators; Phase 4 & 5 provide deterministic policy evaluations and fraud alerts.
- **Upcoming Scope:** Produce formal `docs/drunix_integration_spec.md`, implement live RPC adapter with mutual TLS (mTLS), create `ledger_submissions` persistence queue, and build asynchronous reconciliation worker.


