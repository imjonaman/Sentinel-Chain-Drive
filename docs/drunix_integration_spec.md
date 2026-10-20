# DRUNIX Permissioned-Ledger Integration Specification

## 1. Executive Summary and Architectural Principles

This document establishes the formal integration specification between **Sentinel Chain Drive** and the **DRUNIX** permissioned distributed ledger. 

The integration serves one primary purpose: **verifiable, tamper-evident external state attestation and cross-institution audit proofs**. It does **not** execute financial payments, real-money transactions, or live banking settlements.

### Core Architectural Invariants:
1. **Off-Chain Deterministic Authorization**: All core payment authorization decisions (`ALLOW`, `DECLINE`, `HOLD`, `STEP_UP`) and money mule risk scoring remain strictly **synchronous, deterministic, and off-chain** within the Python platform.
2. **Decoupled Asynchronous Attestation**: A local `ALLOW` authorization decision is complete and final internally; it does **not** block on DRUNIX node availability, network latency, or block confirmation.
3. **Outage Resilience & Zero False Approvals**: If the DRUNIX network is degraded, partitioning, or down, local payment operations continue unimpeded. Ledger attestations queue safely in PostgreSQL. Under no circumstances can a DRUNIX outage or delivery failure reverse an authorization decision or cause an unauthorized transaction to be approved.
4. **Data Minimization & Privacy Preservation**: Ledger submissions contain strictly minimized cryptographic hashes (`SHA-256` commitments) and HMAC pseudonyms (`MeshID`). Plaintext customer names, raw bank account numbers, balances, passwords, credentials, and private keys are **never** transmitted to the ledger.

---

## 2. Integration Safety Boundary

The integration enforces strict separation across six distinct lifecycle concepts:

| Lifecycle Concept | System Location | Persistence & Guarantees |
| :--- | :--- | :--- |
| **1. Internal Authorization Decision** | Core Policy Engine | Synchronous, deterministic outcome (`ALLOW`, `DECLINE`, `HOLD`, `STEP_UP`) committed to `policy_evaluations`. Authoritative. |
| **2. Durable Outbox Intent** | Transactional Outbox | Persisted to `drunix_outbox_events` within the **exact same ACID database transaction** as the internal decision. |
| **3. Submission Attempt** | Asynchronous Worker | Worker claims events using `SELECT ... FOR UPDATE SKIP LOCKED` with bounded exponential backoff, jitter, and Circuit Breaker isolation. |
| **4. External Acknowledgement** | DRUNIX Adapter | Node returns `DRUNIXReceipt` containing transaction hash, block sequence, and raw response metadata. |
| **5. Reconciliation Status** | Reconciliation Engine | Indeterminate outcomes (e.g., timeout after request dispatch) transition to `RECONCILIATION_REQUIRED` without assuming failure. |
| **6. Verified Ledger State** | Verification API | Query verification confirms that the on-chain commitment hash matches the expected database record hash. |

> **Critical Safety Rule**: A local `ALLOW` authorization decision must never be treated as proof of DRUNIX finality. Conversely, an external DRUNIX delivery failure or timeout must never corrupt or invalidate an internal authorization decision.

---

## 3. Replaceable Adapter Architecture

All communication with the DRUNIX distributed ledger is abstracted behind the abstract base class `DRUNIXAdapter` (`src/sentinel_chain_drive/integrations/drunix/adapter.py`).

```python
class DRUNIXAdapter(ABC):
    @abstractmethod
    async def is_available(self) -> bool: ...

    @abstractmethod
    async def record_authorization_attestation(
        self, record_id: str, commitment_hash: str, payload_summary: dict[str, Any] | None = None
    ) -> DRUNIXReceipt: ...

    @abstractmethod
    async def publish_shared_fraud_indicator(
        self, indicator_id: str, payload_hash: str, payload_summary: dict[str, Any] | None = None
    ) -> DRUNIXReceipt: ...

    @abstractmethod
    async def verify_attestation(self, receipt_reference: str, expected_hash: str) -> bool: ...

    @abstractmethod
    async def retrieve_record(self, record_id: str) -> dict[str, Any] | None: ...
```

### Receipt Data Contract:
```python
@dataclass(frozen=True)
class DRUNIXReceipt:
    tx_hash: str
    status: str
    record_id: str
    commitment_hash: str
    block_or_sequence: int | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    adapter_name: str = "drunix_adapter"
    raw_response: dict[str, Any] | None = None
```

---

## 4. Current Implementation: In-Memory Simulator (`MockDRUNIXAdapter`)

The repository currently provides `MockDRUNIXAdapter` (`src/sentinel_chain_drive/integrations/drunix/mock_adapter.py`).

### Simulator Designation:
- `MockDRUNIXAdapter.is_simulator = True`
- Clearly labeled as an **in-memory test simulator**; it does **not** communicate with real blockchain nodes.
- Simulates 10 deterministic failure and edge-case scenarios:
  1. **Normal / Successful Acknowledgement**: Deterministic SHA-256 transaction receipts (`0x...`).
  2. **Temporary Timeout**: `DRUNIXTimeoutError` simulating network disconnect before dispatch.
  3. **Transient Retryable Error**: `DRUNIXTransientError` simulating gateway rate limiting or node busy conditions.
  4. **Terminal Error**: `DRUNIXTerminalError` simulating permanent rejection of invalid parameters.
  5. **Duplicate Idempotency**: Repeated submissions for the same `record_id` return the existing receipt without duplicate ledger entries.
  6. **Uncertain Timeout**: `DRUNIXUncertainOutcomeError` simulating a network partition where the remote node recorded the commitment, but the client connection dropped before receipt arrival.
  7. **Delayed Confirmation**: Receipts return `PENDING_CONFIRMATION` simulating asynchronous mempool admission.
  8. **Worker Interruption Recovery**: Events left in `PROCESSING` state are safely reclaimed after stale lock timeout.
  9. **Reconciliation Verification**: `retrieve_record` returns stored records to resolve uncertain events to `DELIVERED`.
  10. **Malformed Response**: `DRUNIXMalformedResponseError` simulating corrupted payload responses.

---

## 5. Transactional Outbox and Worker Specification

### 5.1 Outbox Schema (`drunix_outbox_events`)
- **Primary Key**: `id` (UUIDv4)
- **Institution Scoping**: `institution_id` (ForeignKey to `institutions.id`, CASCADE, indexed)
- **Idempotency Guarantee**: Unique constraint `uq_drunix_outbox_institution_idempotency` on `(institution_id, idempotency_key)`
- **Event Types**: `AUTH_ATTESTATION`, `FRAUD_INDICATOR`, `SETTLEMENT_RECORD`
- **Statuses**: `PENDING`, `PROCESSING`, `DELIVERED`, `RETRYABLE_FAILURE`, `TERMINAL_FAILURE`, `RECONCILIATION_REQUIRED`
- **Locking Columns**: `locked_by` (worker ID), `locked_at` (UTC timestamp)
- **Backoff Columns**: `attempt_count`, `max_attempts` (default: 5), `next_attempt_at`

### 5.2 PostgreSQL Concurrency & Row-Locking
Multi-worker claiming is serialized safely using:
```sql
SELECT * FROM drunix_outbox_events
WHERE status IN ('PENDING', 'RETRYABLE_FAILURE')
  AND next_attempt_at <= NOW()
  AND (locked_by IS NULL OR locked_at < :stale_threshold)
ORDER BY next_attempt_at ASC
LIMIT :batch_size
FOR UPDATE SKIP LOCKED;
```
This guarantees that concurrent worker instances claim disjoint sets of events without blocking or deadlocking.

### 5.3 Bounded Exponential Backoff with Jitter
```text
delay = min(max_backoff, base_backoff * (backoff_multiplier ^ (attempt - 1))) * uniform(0.8, 1.2)
```
- Base backoff: 1.0 second
- Max backoff: 60.0 seconds
- Max attempts: 5

### 5.4 Circuit Breaker Fault Isolation
- States: `CLOSED` -> `OPEN` -> `HALF_OPEN`
- Failure threshold: 5 consecutive transient/timeout failures trips circuit to `OPEN`.
- Recovery timeout: 30.0 seconds before testing recovery in `HALF_OPEN`.
- Half-open success threshold: 2 consecutive successful trial calls return circuit to `CLOSED`.

---

## 6. What Remains Blocked on Authoritative DRUNIX Protocol Specifications

A live production network adapter cannot be constructed until authoritative specifications are established by DRUNIX consortium leadership. The following technical specifications remain **PENDING**:

| Domain | Required Authoritative Specification | Current Architecture Handling |
| :--- | :--- | :--- |
| **Transport Layer** | Supported network protocols (JSON-RPC 2.0 over HTTP/2, gRPC Protobuf, or WebSockets). Port assignments and endpoint schemas. | Abstracted behind `DRUNIXAdapter` async interface methods. |
| **Authentication & Mutual TLS** | Node authentication standards, client certificate authorities (mTLS), API tokens, or bearer tokens. | No hardcoded credentials; placeholder configuration managed via `Settings`. |
| **Cryptographic Scheme** | Ledger-native signing algorithms (Ed25519, Secp256k1, Dilithium post-quantum) and transaction packaging formats. | Clean separation; commitments use SHA-256 hashes of canonical state strings. |
| **Consensus & Finality** | Consensus model (PBFT, Raft, Proof-of-Authority) and finality depth guarantees (instant finality vs N confirmations). | Local decisions are immediately authoritative; outbox handles eventual ledger delivery. |
| **Smart-Contract Semantics** | Smart contract execution engine (Wasm, EVM, native chaincode) and ABI definitions for state attestation. | Off-chain Python deterministic engine; zero assumed EVM/Solidity dependencies. |
| **Receipt Schema** | Structure of transaction receipts, event logs, and block headers returned by nodes. | Standardized `DRUNIXReceipt` dataclass capturing external transaction hashes and sequences. |

---

## 7. Operational Observability

Sanitized health and metrics are exposed via:
`GET /api/v1/drunix/status`
- Circuit breaker state (`CLOSED`, `OPEN`, `HALF_OPEN`)
- Outbox event counts by status (`PENDING`, `PROCESSING`, `DELIVERED`, `RETRYABLE_FAILURE`, `TERMINAL_FAILURE`, `RECONCILIATION_REQUIRED`)
- Oldest pending event latency (seconds)
- Node liveness probe status
- Timestamp of last successful delivery
- Strictly redact all credentials, keys, and transaction payload contents.
