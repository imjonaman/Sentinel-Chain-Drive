# 🛡️ Sentinel Chain Drive — Testing & Verification Walkthrough

Welcome to the comprehensive testing and verification guide for **Sentinel Chain Drive** — a high-assurance, multi-tenant agentic banking platform built with deterministic policy evaluation, Ed25519 cryptographic credentials, privacy-preserving graph analytics (MuleChain), and transactional outbox ledger integration (DRUNIX).

This document details all test suites, live API tests, frontend interactive operator flows, and failure injection scenarios available in this repository.

---

## 📋 Table of Contents
1. [Prerequisites & Environment Setup](#1-prerequisites--environment-setup)
2. [Automated Backend Test Suites (pytest)](#2-automated-backend-test-suites-pytest)
3. [Interactive Backend API Testing (Swagger / OpenAPI)](#3-interactive-backend-api-testing-swagger--openapi)
4. [Interactive Frontend Operator Dashboard Testing](#4-interactive-frontend-operator-dashboard-testing)
   - [4.1 Multi-Role Lifecycle Scenario (All 4 Operator Personas)](#41-multi-role-lifecycle-scenario-all-4-operator-personas)
   - [4.2 Individual Component & Feature Tests](#42-individual-component--feature-tests)
5. [Automated Frontend Unit & E2E Tests](#5-automated-frontend-unit--e2e-tests)
6. [Fault Tolerance & Security Failure Injection Tests](#6-fault-tolerance--security-failure-injection-tests)
7. [Quick Reference Test Cheat Sheet](#7-quick-reference-test-cheat-sheet)

---

## 1. Prerequisites & Environment Setup

### 1.1 Verify Python and Node.js Environments
From the repository root (`d:\Sentinel-Chain-Drive`):

```powershell
# Verify Python virtual environment (Python 3.13)
.\.venv\Scripts\python.exe --version

# Verify Node.js and npm
node -v
npm -v
```

### 1.2 Verify Database Migrations & Seeds
The local environment is configured with SQLite (`sentinel.db`) with synthetic bank institutions and accounts:
```powershell
# Ensure database schema is up to date
.\.venv\Scripts\alembic.exe upgrade head
```

### 1.3 Start the Services

#### Start the Backend API Server:
```powershell
# In Terminal 1 (from d:\Sentinel-Chain-Drive):
.\.venv\Scripts\uvicorn.exe sentinel_chain_drive.api.main:app --reload --port 8000
```
* **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
* **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
* **OpenAPI JSON:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

#### Start the Frontend Operator Dashboard:
```powershell
# In Terminal 2 (from d:\Sentinel-Chain-Drive\frontend):
cd frontend
& "C:\Program Files\nodejs\npm.cmd" run dev
```
* **Frontend Dashboard:** [http://localhost:5173](http://localhost:5173)

---

## 2. Automated Backend Test Suites (pytest)

The backend features **239 tests** covering unit domains, integration pipelines, cryptographic contracts, concurrency, and privacy gateways.

### 2.1 Run the Full Test Suite
```powershell
.\.venv\Scripts\pytest.exe -v
```
*(All 239 tests pass with 100% success rate).*

---

### 2.2 Domain-Specific Test Suites

#### A. Banking State Machine & Idempotency Tests
Tests exact Decimal arithmetic, idempotency key deduplication, balance consistency, and state transitions (`PENDING_AUTHORIZATION` ➔ `SETTLED` / `HELD` / `REJECTED`):
```powershell
.\.venv\Scripts\pytest.exe tests/integration/test_transactions_api.py tests/unit/test_banking_domain.py -v
```

#### B. Autonomous AgentID Registry & Ed25519 Crypto Tests
Tests Ed25519 RFC 8032 signature verification, key rotation version incrementing, and capability envelopes:
```powershell
.\.venv\Scripts\pytest.exe tests/integration/test_agent_id_api.py tests/unit/test_crypto.py tests/unit/test_agent_domain.py -v
```

#### C. Deterministic 7-Tier Policy Precedence Hierarchy Tests
Verifies strict evaluation order (Security Violations > Account Frozen > Agent Limits > Institutional Caps > MuleChain Risk > Dual-Control Step-Up > Default Allow):
```powershell
.\.venv\Scripts\pytest.exe tests/integration/test_policy_api.py tests/unit/test_policy_engine.py tests/unit/test_policy_models.py -v
```

#### D. MuleChain Graph Fraud Detectors Tests
Tests topological detection algorithms: Fan-In Smurfing, Fan-Out Dispersal, Rapid Pass-Through, and Circular Layering:
```powershell
.\.venv\Scripts\pytest.exe tests/integration/test_mulechain_api.py tests/unit/test_mulechain_detectors.py tests/unit/test_mulechain_scoring.py -v
```

#### E. Privacy Gateway & k-Anonymity Tests
Verifies differential privacy noise injection, $k$-anonymity bucket constraints ($k \ge 5$), and rejection of prohibited PII fields:
```powershell
.\.venv\Scripts\pytest.exe tests/integration/test_privacy_gateway_api.py tests/unit/test_privacy_core.py tests/unit/test_privacy_gateway_service.py -v
```

#### F. DRUNIX Transactional Outbox & Circuit Breaker Tests
Tests at-least-once outbox relay worker, retry policies with exponential backoff, and 3-state circuit breaker (`CLOSED` ➔ `OPEN` ➔ `HALF_OPEN`):
```powershell
.\.venv\Scripts\pytest.exe tests/integration/test_drunix_concurrency.py tests/unit/test_drunix_outbox.py -v
```

#### G. Tamper-Evident Audit Trail & Redaction Tests
Verifies that all audit logs strip plaintext passwords, private keys, PANs, and session tokens before persisting:
```powershell
.\.venv\Scripts\pytest.exe tests/integration/test_audit_repository.py tests/unit/test_middleware_and_logging.py -v
```

---

## 3. Interactive Backend API Testing (Swagger / OpenAPI)

Open **[http://localhost:8000/docs](http://localhost:8000/docs)** in your browser to execute API calls interactively.

### Test 3.1: Platform Health & Liveness Checks
* **Endpoint:** `GET /health/live` and `GET /health/ready`
* **Expected Result:**
  ```json
  {
    "status": "healthy",
    "database": "connected",
    "circuit_breaker": "CLOSED",
    "timestamp": "2026-10-22T..."
  }
  ```

---

### Test 3.2: Submit Payment with Idempotency Verification
* **Endpoint:** `POST /api/v1/transactions`
* **Payload:**
  ```json
  {
    "idempotency_key": "test-key-001",
    "origin_institution_id": "10000000-0000-0000-0000-000000000001",
    "origin_account_id": "20000000-0000-0000-0000-000000000001",
    "destination_institution_id": "10000000-0000-0000-0000-000000000001",
    "destination_account_id": "20000000-0000-0000-0000-000000000002",
    "amount": "1250.5000",
    "currency": "USD",
    "purpose_code": "INVOICE_SETTLEMENT"
  }
  ```
* **Step 1:** Click **Execute**. Status returned: `201 Created` with `status: "PENDING_AUTHORIZATION"`.
* **Step 2 (Idempotency Test):** Click **Execute** again with the exact same payload.
* **Verification:** The API returns the exact existing transaction record without duplicate creation or duplicate debit.

---

### Test 3.3: Autonomous Agent Registration & Key Rotation
* **Endpoint:** `POST /api/v1/agents`
* **Payload:**
  ```json
  {
    "institution_id": "10000000-0000-0000-0000-000000000001",
    "name": "Treasury Arbitrage Bot",
    "description": "High-frequency nostro settlement agent",
    "ed25519_public_key": "a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890"
  }
  ```
* **Step 1:** Click **Execute**. Agent created with `key_version: 1` and status `ACTIVE`.
* **Step 2 (Key Rotation):** Call `POST /api/v1/agents/{id}/rotate-key` with a new 64-character public key.
* **Verification:** Key version increments to `2` and previous signatures are invalidated.

---

### Test 3.4: 7-Tier Policy Rule Precedence Simulation
* **Endpoint:** `POST /api/v1/policy/evaluate`
* **Test Case A (Step-Up Dual-Control Trigger):**
  * Submit transaction amount `$75,000.00` (exceeds supervisor threshold `$50,000.00`).
  * **Result:** `outcome: "STEP_UP"`, `evaluating_tier: 6`.
* **Test Case B (Capability Violation):**
  * Submit transaction amount `$15,000.00` under an agent with `$10,000.00` per-tx cap.
  * **Result:** `outcome: "DECLINE"`, `evaluating_tier: 3`.

---

### Test 3.5: Privacy Gateway Differential Privacy Query
* **Endpoint:** `POST /api/v1/privacy/publish-indicator`
* **Payload (Approved Indicator):**
  ```json
  {
    "subject_mesh_id": "mesh-abc-12345",
    "risk_level": "SUSPICIOUS",
    "hop_count": 3
  }
  ```
* **Verification:** Successfully published with differential noise and HMAC anonymization.
* **Negative Test (Prohibited PII Rejection):** Attempt to include `"raw_account_number": "123456789"`.
* **Result:** `422 Unprocessable Content` with `PROHIBITED_FIELD_REJECTED`.

---

## 4. Interactive Frontend Operator Dashboard Testing

Launch the UI at **[http://localhost:5173](http://localhost:5173)**.

---

### 4.1 Multi-Role Lifecycle Scenario (All 4 Operator Personas)

This continuous scenario demonstrates how **Security Administrators**, **Bank Operators**, **Fraud Analysts**, and **Compliance Auditors** collaborate within Sentinel Chain Drive to safely govern, execute, screen, and audit an autonomous banking operation.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                       END-TO-END MULTI-ROLE OPERATIONAL WORKFLOW                            │
├──────────────────────────┬──────────────────────────┬──────────────────────────┬────────────┤
│ 1. SECURITY ADMIN        │ 2. BANK OPERATOR         │ 3. FRAUD ANALYST         │ 4. AUDITOR │
│ Register AgentID & Keys  │ Submit Payment Intent    │ Screen Graph Topology    │ Verify Log │
│ Enforce Envelope Caps    │ Trigger State Machine    │ Triage MuleChain Loop    │ Merkle Root│
│ Simulate Precedence Tier │ Finalize Settlement      │ Escalate Formal Case     │ Outbox CB  │
└──────────────────────────┴──────────────────────────┴──────────────────────────┴────────────┘
```

#### 🎭 Act 1: Security Administrator — Provision Agent & Bound Envelope
* **Persona Goal:** Authorize an autonomous liquidity agent with strict Ed25519 cryptographic credentials and deterministic capability bounds.
* **Steps:**
  1. In the top navigation bar, ensure the active tenant is set to **Apex Reserve Bank** (`APEXUS33`).
  2. Click the **Operator Role Selector** and switch to **Security Administrator**.
  3. Navigate to **AgentID Registry** (`/security/agents`) in the sidebar.
  4. Click **Register New Agent** to launch the wizard:
     * **Name:** `Apex Autonomous Liquidity Bot`
     * **Description:** `Automated overnight inter-bank settlement rebalancer`
     * **Key Generation:** Click **Generate Test Key** to create a valid 64-hex RFC 8032 public key.
     * **Limits:** Set **Max Amount Per Transaction** to `$20,000.00` and **Daily Cumulative** to `$100,000.00`.
     * Click **Register Agent**.
  5. On the generated agent card, click the **Copy** button next to the Ed25519 key (note the instant green "Copied!" toast).
  6. Navigate to **Policy Simulator** (`/security/policies`):
     * Test amount `$15,000.00` ➔ Status: **ALLOW** (clean Tier 7 allow; within envelope).
     * Test amount `$65,000.00` ➔ Status: **STEP_UP** (evaluating Tier 6; triggers supervisor dual-custody).
* **Tangible Output:** Autonomous agent credentialed with active Ed25519 key version 1 and locked within deterministic mathematical constraints.

---

#### 🎭 Act 2: Bank Operator — Execute Payment & Settle State Machine
* **Persona Goal:** Submit an inter-bank payment and advance it through the financial state machine with strict idempotency.
* **Steps:**
  1. Click the **Operator Role Selector** in the navbar and switch to **Bank Operator**.
  2. Navigate to **Queue & Settlement** (`/operator/transactions`).
  3. Click **Submit Transaction**:
     * **Origin Account:** Select primary nostro account (`···0001`).
     * **Destination Account:** Select counterparty account (`···0002`).
     * **Amount ($):** `15000.00`
     * **Purpose Code:** `TREASURY_REBALANCE`
     * Click **Submit Transaction**.
  4. Notice the instant visual feedback banner: `Transaction PENDING_AUTHORIZATION: ID ...`.
  5. Locate the newly created row in the queue table:
     * Status displays yellow `PENDING_AUTHORIZATION` badge.
     * Actions available: `Settle`, `Hold`, `Reject`.
  6. Click the green **Settle** button.
* **Tangible Output:** Real-time state machine transition from `PENDING_AUTHORIZATION` to `SETTLED`. Glowing green badge displays `Settlement Final` with exact Decimal precision guaranteed.

---

#### 🎭 Act 3: Fraud Analyst — Multigraph Analysis & Case Escalation
* **Persona Goal:** Investigate a potential synthetic money-laundering loop detected across the inter-bank network.
* **Steps:**
  1. Click the **Operator Role Selector** and switch to **Fraud Analyst**.
  2. Navigate to **Alert Triage** (`/fraud/alerts`):
     * Observe the top alert `ALT-20261022-0042` with **Risk Score 92** (Critical) flagged by detector `CIRCULAR_LAYERING`.
  3. Click **Graph Node** or navigate to **Graph Explorer** (`/fraud/graph`):
     * In the node search input, enter `20000000-0000-0000-0000-000000000002`.
     * Notice the Cytoscape graph smoothly auto-pans, zooms in, and rings the target node with a pulsing cyan indicator.
     * Switch layouts using the layout selector buttons (`cose` ➔ `concentric` ➔ `circle`) to inspect the 3-hop cyclic fund path (`Acc-01 ➔ Acc-02 ➔ Acc-03 ➔ Acc-01`).
     * Click on the directed edge between nodes to open the sliding inspection panel detailing edge weight, token volume, and velocity.
  4. Return to **Alert Triage** (`/fraud/alerts`) and click **Escalate to Case**:
     * **Investigation Title:** `Investigation: High-Velocity Circular Layering Loop`
     * **Notes:** `MuleChain detected a closed-cycle fund flow across accounts within a 2-hour window. Escalating to compliance for freeze evaluation.`
     * Click **Open Formal Case**.
* **Tangible Output:** Formal compliance investigation case created and bound to the sanitized graph evidence payload.

---

#### 🎭 Act 4: Compliance Auditor — Cryptographic Audit & Ledger Outbox
* **Persona Goal:** Inspect the tamper-evident audit logs to verify sensitive data sanitization and inspect the DRUNIX outbox ledger.
* **Steps:**
  1. Click the **Operator Role Selector** and switch to **Compliance Auditor**.
  2. Navigate to **Audit Inspector** (`/audit/logs`):
     * Confirm the green header badge: **Merkle Chain: VALIDATED ✓**.
     * In the search input, type `TRANSACTION`.
     * Inspect the **Redacted Fields** column: Verify that sensitive items (`raw_pan`, `private_key`, `credentials`) are rendered with amber eye-off redaction pills (`[REDACTED]`), proving zero sensitive data leaks.
     * Review the SHA-256 hash proof string attached to each immutable audit event.
  3. Navigate to **DRUNIX Telemetry** (`/audit/drunix`):
     * Review the **Circuit Breaker** state: Displays green **CLOSED** with 0 consecutive failures.
     * Verify the **Outbox Completed** counter confirms at-least-once ledger commit delivery.
     * Note the latency indicator showing average commit latency `<20ms`.
* **Tangible Output:** Cryptographic proof of data minimization compliance and ledger outbox synchronization health without single-point-of-failure vulnerabilities.

---

### 4.2 Individual Component & Feature Tests

The following individual tests allow targeted verification of specific UI components:

### Test 4.2.1: Multi-Tenant Switching
1. In the top navigation bar, locate the **Institution Tenant Selector**.
2. Switch between **Apex Reserve Bank** (`APEXUS33`), **Meridian Trust Corp** (`MRDNUS33`), and **Obsidian Clearing** (`OBSDUS33`).
3. **Verification:** All account balances, transactions, and metrics refresh immediately scoped to the selected institution.

---

### Test 4.2.2: Role-Aware Persona Switching
1. In the top navigation bar, click the **Operator Role Selector**.
2. Select each of the 4 roles:
   * **Bank Operator:** Access to Payment Submission, Queue Settle/Hold/Reject.
   * **Security Administrator:** Access to AgentID Registry, Capability Sliders, Policy Rules.
   * **Fraud Analyst:** Access to Directed Multigraph, Anomaly Detector, Case Escalation.
   * **Compliance Auditor:** Access to Tamper-Evident Audit Trail, Redaction Inspector, DRUNIX Telemetry.
3. **Verification:** Navigation items and view permissions reconfigure instantly.

---

### Test 4.2.3: Financial State Machine & Queue Settlement
1. Switch role to **Bank Operator** and navigate to **Queue & Settlement** (`/operator/transactions`).
2. Click **Submit Transaction**. Fill in:
   * Amount: `$5,000.00`
   * Purpose: `EQUIPMENT_LEASE`
3. Click **Submit Transaction**.
4. Observe the transaction appear in the table with `PENDING_AUTHORIZATION`.
5. Click the green **Settle** button.
6. **Verification:** Status transitions to `SETTLED`, glowing badge turns green, and "Settlement Final" indicator displays.

---

### Test 4.2.4: AgentID Registration Wizard & Capability Sliders
1. Switch role to **Security Administrator** and navigate to **AgentID Registry** (`/security/agents`).
2. Click **Register New Agent**.
   * Step 1: Name: `FX Liquidity Rebalancer`
   * Step 2: 64-hex Ed25519 Key (use the built-in "Generate Valid Test Key" button).
   * Step 3: Set Max per-transaction limit to `$25,000` and Daily Cumulative limit to `$100,000`.
3. Submit and verify the agent card is generated with its RFC 8032 key.
4. Click **Copy** next to the public key. Notice the instant "Copied!" feedback pill.
5. Click **Limits** to adjust the interactive capability sliders in real-time.

---

### Test 4.2.5: Directed Multigraph Visualizer (Cytoscape.js)
1. Switch role to **Fraud Analyst** and navigate to **Graph Explorer** (`/fraud/graph`).
2. **Layout Controls:** Click the layout buttons (`cose`, `concentric`, `circle`, `breadthfirst`). Observe the smooth animated node repositioning.
3. **Interactive Search:** In the node search box, type a node ID (e.g., `20000000`). Notice the auto-pan, zoom, and pulsating highlight ring.
4. **Element Inspection:** Click any node or edge to inspect exact account risk scores, inbound/outbound edge weights, and currency volumes in the sliding inspector card.

---

### Test 4.2.6: MuleChain Alert Triage & Formal Case Escalation
1. Navigate to **Alert Triage** (`/fraud/alerts`).
2. Review the topological anomaly alerts (Rapid Pass-Through, Circular Layering) with risk scores.
3. Filter by **Critical (Risk >= 80)**.
4. Click **Escalate to Case**.
5. Enter a case title and description, then click **Open Formal Case**.
6. **Verification:** Success banner confirms case assignment to the compliance team.

---

### Test 4.2.7: Tamper-Evident Audit Trail & PII Redaction Verification
1. Switch role to **Compliance Auditor** and navigate to **Audit Inspector** (`/audit/logs`).
2. Observe the **Merkle Chain: VALIDATED ✓** integrity badge.
3. Inspect the **Redacted Fields** column: Verify that sensitive tokens, PANs, and private keys display the amber eye-off redaction pill (`[REDACTED]`).
4. In the search bar, filter by `STEP_UP_CHALLENGE_APPROVED` or correlation ID.

---

### Test 4.2.8: DRUNIX Ledger Outbox & Circuit Breaker Telemetry
1. Navigate to **DRUNIX Telemetry** (`/audit/drunix`).
2. Review live counters:
   * **Circuit Breaker:** `CLOSED` (Healthy, 0 failures)
   * **Outbox Completed:** At-least-once committed count
   * **Pending Queue:** Events waiting for worker dispatch
   * **Active Adapter:** Simulator mode
3. Check the visual explanation of the 3-state state machine (`CLOSED` ➔ `OPEN` ➔ `HALF_OPEN`).

---

## 5. Automated Frontend Unit & E2E Tests

### 5.1 Vitest Component Tests
Tests Zod schemas, form validations, and role-based access rules:
```powershell
cd d:\Sentinel-Chain-Drive\frontend
& "C:\Program Files\nodejs\npm.cmd" run test
```

### 5.2 TypeScript Build & Bundle Validation
Ensures strict type checking without warnings or unused variables:
```powershell
& "C:\Program Files\nodejs\npm.cmd" run build
```

### 5.3 Playwright End-to-End Tests
Runs headless browser simulation of all operator workflows:
```powershell
& "C:\Program Files\nodejs\npm.cmd" run test:e2e
```

---

## 6. Fault Tolerance & Security Failure Injection Tests

### Test 6.1: Concurrent Idempotency Race Condition
Simulates 20 concurrent identical payment requests dispatched in parallel:
```powershell
.\.venv\Scripts\pytest.exe tests/integration/test_event_ordering_concurrency.py -v
```
* **Guarantee:** Exactly 1 payment settles; the remaining 19 receive idempotent references without duplicate debits.

---

### Test 6.2: DRUNIX Circuit Breaker Tripping Under Network Failure
Simulates external ledger timeout failures:
```powershell
.\.venv\Scripts\pytest.exe tests/integration/test_drunix_concurrency.py -k "test_circuit_breaker" -v
```
* **Guarantee:** After 5 consecutive transient network errors, the breaker transitions to `OPEN`. Outbox events are safely persisted in PostgreSQL/SQLite without data loss. After cooldown, single-probe `HALF_OPEN` resets to `CLOSED`.

---

### Test 6.3: Tamper-Proof Cryptographic Signature Verification
Tests forged Ed25519 signature payload injection:
```powershell
.\.venv\Scripts\pytest.exe tests/unit/test_crypto.py -k "test_tampered_signature_rejected" -v
```
* **Guarantee:** Any single bit alteration in payload or signature causes immediate `SECURITY_VIOLATION` decline at Tier 1.

---

## 7. Quick Reference Test Cheat Sheet

| Test Category | Target Component | Command / URL |
| :--- | :--- | :--- |
| **All Backend Tests** | Full 239 test suite | `.\.venv\Scripts\pytest.exe -v` |
| **API Documentation** | Swagger UI Interactive | `http://localhost:8000/docs` |
| **Frontend Dashboard** | Vite Operator UI | `http://localhost:5173` |
| **Frontend Build** | TypeScript + Vite Bundle | `cd frontend; npm run build` |
| **Frontend Tests** | Vitest unit tests | `cd frontend; npm run test` |
| **Policy Engine** | 7-Tier Precedence Suite | `pytest tests/integration/test_policy_api.py -v` |
| **Fraud Graph** | MuleChain Detectors | `pytest tests/unit/test_mulechain_detectors.py -v` |
| **Outbox Relay** | DRUNIX Concurrency | `pytest tests/integration/test_drunix_concurrency.py -v` |
| **Privacy Gateway** | k-Anonymity & PII Masking | `pytest tests/integration/test_privacy_gateway_api.py -v` |

---
*Generated for Sentinel Chain Drive — Production Ready Verification Reference.*
