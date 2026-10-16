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
