# Sentinel Chain Drive - Architecture Overview

## 1. System Vision & Scope

Sentinel Chain Drive is an AI-agent authorization and cross-bank fraud intelligence platform designed to address:
1. **Agentic Payment Risks**: Autonomous AI agents initiating unauthorized or out-of-policy financial transfers.
2. **Cross-Bank Mule Networks**: Fragmented transaction visibility across financial institutions concealing coordinated fraud and illicit fund movements.

**Phase 1** establishes the secure software foundation for the platform without introducing premature external dependencies or unverified network integrations.

---

## 2. Core Architecture & Layer Separation

```
                       +-----------------------+
                       |   HTTP Client / Agent |
                       +-----------+-----------+
                                   |
                                   v
             +-------------------------------------------+
             |            Middleware Stack               |
             | - Security Headers (nosniff, DENY, etc.)  |
             | - Request Size Limiter (HTTP 413, 1MB)    |
             | - Correlation ID (X-Correlation-ID)       |
             | - Conservative CORS (strict origin list)  |
             +---------------------+---------------------+
                                   |
                                   v
             +-------------------------------------------+
             |                 API Layer                 |
             |  /health/live   /health/ready             |
             |  /api/v1/system/info                      |
             +---------------------+---------------------+
                                   |
                                   v
             +-------------------------------------------+
             |              Services Layer               |
             |  - SystemService (Health probes & meta)   |
             |  - AuditService (Event lifecycle)         |
             +----------+---------------------+----------+
                        |                     |
                        v                     v
+-------------------------------+   +------------------------------------+
|       Repositories Layer      |   |        Integrations Layer          |
|  - AuditRepository            |   |  - DRUNIXAdapter (Interface)       |
|  - Parameterized ORM Access   |   |  - MockDRUNIXAdapter (Phase 1 Stub)|
+---------------+---------------+   +------------------------------------+
                |
                v
+-------------------------------+
|      Database (PostgreSQL)    |
|  - Async SQLAlchemy 2.x       |
|  - Alembic Migrations         |
+-------------------------------+
```

### Key Architectural Boundaries

1. **API Layer (`src/sentinel_chain_drive/api/`)**:
   - Manages routing, input parsing, dependency injection, and HTTP status codes.
   - Contains no database SQL statements and no direct business logic.

2. **Core & Security Layer (`src/sentinel_chain_drive/core/`)**:
   - `config.py`: Validated settings via Pydantic Settings. Sensitive credentials (`POSTGRES_PASSWORD`) use `SecretStr` and are masked in representations.
   - `logging.py`: Structured JSON logging with automatic redaction of tokens, passwords, authorization headers, and private keys.
   - `middleware.py`: Enforces request payload size limits and binds a request correlation ID across contextvars and response headers.
   - `errors.py`: Global exception handlers shielding internal traces, database paths, and sensitive exceptions.

3. **Service Layer (`src/sentinel_chain_drive/services/`)**:
   - Orchestrates domain business rules and multi-step operations.
   - Coordinates repository interactions and external integration adapters.

4. **Persistence Layer (`src/sentinel_chain_drive/repositories/` & `db/`)**:
   - Parameterized access via SQLAlchemy 2.x async engine (`asyncpg`).
   - Session lifecycle managed with automatic commit/rollback context boundaries.
   - Alembic schema migrations maintain reproducible version control over database schemas.

5. **Integration Layer (`src/sentinel_chain_drive/integrations/`)**:
   - `drunix/`: Future distributed ledger operations are kept strictly behind the `DRUNIXAdapter` abstract base class.
   - Phase 1 provides `MockDRUNIXAdapter` which stores records in-memory and produces deterministic transaction hashes without making external network calls.

---

## 3. Request Correlation & Observability

Every incoming HTTP request is assigned a unique `X-Correlation-ID` (or adopts a valid client-supplied ID). This ID is:
- Bound to Python's `contextvars` context.
- Included in all structured JSON log records emitted during the request.
- Returned to the client in the `X-Correlation-ID` response header.
- Embedded in error payloads for immediate cross-referencing in server logs.

---

## 4. Database Strategy & Migrations

- **Authoritative Operational Datastore**: PostgreSQL 16+.
- **Driver Dialect**:
  - Application runtime: `postgresql+asyncpg` for non-blocking asynchronous concurrency.
  - Migrations: `postgresql+psycopg` for reliable synchronous schemaDDL execution.
- **Migration Commands**:
  - `alembic upgrade head`: Apply pending migrations.
  - `alembic downgrade -1`: Roll back the last migration.

---

## 5. Phase 2: Simulated Banking Environment & Transaction Domain

Phase 2 establishes a secure, deterministic, multi-institution simulation environment that provides the data models and API contracts required by future authorization (Phase 3) and fraud detection (Phase 4) phases.

### 5.1 Institutions Management
- **Model**: `Institution` with `institution_code`, `routing_identifier`, `status` (`ACTIVE`, `SUSPENDED`, `INACTIVE`), and `settings`.
- **Transitions**: Controlled state transitions (`ACTIVE` <-> `SUSPENDED`, `ACTIVE` -> `INACTIVE`). `INACTIVE` is terminal.
- **Tenant Isolation**: Institution records define the root multi-tenant boundaries. Cross-institution operations require explicit authorization.

### 5.2 Accounts Management
- **Model**: `Account` associated with an `Institution`.
- **Monetary Safety**: Exact `Numeric(18, 4)` precision. Floating-point arithmetic is strictly prohibited. Database check constraint enforces `balance >= 0`.
- **State Machine**: `ACTIVE` <-> `FROZEN`, `ACTIVE` -> `CLOSED`. `CLOSED` is terminal.
- **Isolation**: Tenant header `X-Institution-ID` prevents unauthorized cross-tenant account queries (HTTP 403).

### 5.3 Transaction Domain & Gateway
- **Submission State**: Transactions are submitted into `PENDING_AUTHORIZATION`. They are **never** auto-authorized or settled upon submission, preserving the boundary for AgentID policy decisions.
- **Idempotency Semantics**:
  - Idempotency key uniqueness enforced at both database constraint and service level.
  - Exact retry with matching parameters returns existing transaction (HTTP 200).
  - Retry with identical key but conflicting parameters returns HTTP 409 (`IDEMPOTENCY_CONFLICT`).
- **Validation**: Strict validation of positive amounts, supported currency matching, account existence, institution ownership, and operational account/institution states.
- **Auditability**: `TransactionStatusHistory` table atomically logs every transition with timestamps, prior/new status, rationale, and actor.
- **Simulation Lifecycle Gateway**: `/api/v1/transactions/{id}/simulate-action` exposes explicit simulation controls (`SIMULATE_HOLD`, `SIMULATE_SETTLE`, `SIMULATE_REJECT`, `CANCEL`), preventing clients from arbitrarily updating privileged transaction states directly.

### 5.4 Synthetic Data Generation
- Deterministic seed script (`sentinel_chain_drive.db.seed`) populates multi-institution environments (Apex Bank, Beacon Trust, Crestline Bank, Dormant Mutual) and realistic synthetic accounts and transactions. All data is clearly flagged with synthetic metadata.

