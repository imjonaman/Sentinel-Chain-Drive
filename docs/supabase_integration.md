# Supabase PostgreSQL Integration Guide

## 1. Assessment & Architectural Overview

Sentinel Chain Drive uses **SQLAlchemy 2.x (asyncio)** and **Alembic** as its foundational data-access and migration layer. The database models, schemas, and workflows implemented in Phase 1 (Core Foundation) and Phase 2 (Simulated Banking Environment & Transaction Domain) are 100% compliant standard PostgreSQL DDL and async queries, making them natively compatible with **Supabase PostgreSQL**.

### Key Architectural Invariants:
1. **FastAPI Data-Access Boundary:**
   The FastAPI application backend serves as the **sole authorized gateway** to the database. External clients (including future React frontend interfaces) must **never** connect directly to the Supabase database via PostgREST, direct SQL, or client-side Supabase SDKs. All reads, writes, institution boundary checks, idempotency verification, and state transitions must flow through FastAPI versioned REST endpoints (`/api/v1/*`).
2. **Standard PostgreSQL Protocols:**
   No Supabase-specific client SDKs (`@supabase/supabase-js`, `supabase-py`) are introduced into the backend. The integration uses standard PostgreSQL wire protocol drivers (`asyncpg` for async runtime queries, `psycopg 3` for synchronous Alembic migrations).
3. **Environment-Driven Configuration:**
   All connection parameters and secrets remain strictly in environment variables (`DATABASE_URL`, `ALEMBIC_DATABASE_URL`). No secrets or project references are committed to source control.

---

## 2. Supabase Connection Modes & Configuration

Supabase provides two primary connection strings in **Project Settings &rarr; Database**:

### A. Direct Connection (Port 5432)
- **Protocol:** Standard direct PostgreSQL connection.
- **Port:** `5432`
- **Use Cases:**
  - Running Alembic migrations (`alembic upgrade head`).
  - Running deterministic synthetic seed scripts (`python -m sentinel_chain_drive.db.seed`).
  - Low-concurrency standalone development or dedicated VM environments with IPv6/IPv4 support.
- **Connection URL Format:**
  ```env
  DATABASE_URL=postgresql+asyncpg://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres?ssl=require
  ```

### B. Connection Pooler / Supavisor (Port 6543)
- **Protocol:** Transaction-mode connection pooling.
- **Port:** `6543`
- **Use Cases:**
  - High-concurrency production deployments (e.g. serverless containers, container auto-scaling).
  - Environments with IPv4 limitations (Supavisor poolers provide dedicated IPv4 endpoints).
- **Connection URL Format:**
  ```env
  DATABASE_URL=postgresql+asyncpg://postgres.[PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?ssl=require
  ```

---

## 3. Critical Driver & Pooler Compatibility Settings

When connecting through Supabase's transaction pooler (port 6543), two critical considerations must be observed:

### 1. Prepared Statement Cache (`POSTGRES_STATEMENT_CACHE_SIZE=0`)
- **Problem:** By default, `asyncpg` enables prepared statement caching. Transaction poolers (PgBouncer / Supavisor) route consecutive queries across different backend connections, causing prepared statement execution to fail with `prepared statement "_asyncpg_stmt_..." does not exist`.
- **Solution:** Sentinel Chain Drive's database engine automatically detects port `6543`, `pooler`, or `pgbouncer=true` in `DATABASE_URL` and disables prepared statement caching (`statement_cache_size=0`). You can also explicitly configure this via:
  ```env
  POSTGRES_STATEMENT_CACHE_SIZE=0
  ```

### 2. Client-Side Connection Pooling (`POSTGRES_USE_NULL_POOL`)
- When using Supabase's external pooler, maintaining a large persistent client-side pool in FastAPI can unnecessarily consume Supabase connection limits.
- Set `POSTGRES_USE_NULL_POOL=true` if running in ephemeral serverless containers, or tune `POSTGRES_POOL_SIZE=5` and `POSTGRES_MAX_OVERFLOW=5` for standard deployments.

### 3. Dedicated Migration URL (`ALEMBIC_DATABASE_URL`)
- **Critical Requirement:** Database migrations (DDL statements, schema alterations, and `alembic_version` lock updates) require session-level locks and transaction control. They should **never** be executed through a transaction pooler.
- Configure `ALEMBIC_DATABASE_URL` pointing to the direct port 5432 connection:
  ```env
  ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres?sslmode=require
  ```

---

## 4. Migration & Seeding Procedures on a Clean Supabase Database

### Step 1: Configure `.env`
Create a `.env` file containing your Supabase project credentials (never commit this file):
```env
ENVIRONMENT=development
DATABASE_URL=postgresql+asyncpg://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres?ssl=require
ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres?sslmode=require
```

### Step 2: Apply Alembic Migrations
Run Alembic against the clean Supabase PostgreSQL instance:
```powershell
alembic upgrade head
```
*Expected Output:*
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 20261016_0001, Initial audit log schema
INFO  [alembic.runtime.migration] Running upgrade 20261016_0001 -> 20261016_0002, Banking and transaction domain schema
```

### Step 3: Populate Deterministic Synthetic Seed Data
Execute the idempotent seed script:
```powershell
python -m sentinel_chain_drive.db.seed
```
*Creates 4 synthetic institutions, 7 synthetic accounts, and 4 simulated transactions with full audit history.*

### Step 4: Verify Application Connectivity
Start the server and probe readiness:
```powershell
uvicorn sentinel_chain_drive.api.main:app --reload
```
Check readiness:
```powershell
curl http://localhost:8000/health/ready
```
*Expected Response: `{"status": "ready", "dependencies": {"database": "healthy"}}`.*

---

## 5. Development Data Backup & Restoration

To migrate existing local PostgreSQL data to Supabase or create backups:

### Exporting Local PostgreSQL Data
```powershell
# Export schema and data in compressed custom format
pg_dump -h localhost -p 5432 -U sentinel_user -d sentinel_chain_drive -F c -b -v -f sentinel_backup.dump

# Alternatively, export data-only as SQL inserts
pg_dump -h localhost -p 5432 -U sentinel_user -d sentinel_chain_drive --data-only --inserts -f sentinel_data.sql
```

### Restoring into Supabase PostgreSQL
```powershell
# Restore into Supabase via direct connection (port 5432)
pg_restore -h db.[PROJECT-REF].supabase.co -p 5432 -U postgres -d postgres -v sentinel_backup.dump
```

---

## 6. Preservation of Core System Invariants

When running on Supabase PostgreSQL, all platform security and domain invariants remain strictly enforced by the codebase:
- **Monetary Safety:** Financial amounts are stored using PostgreSQL `NUMERIC(18, 4)` and evaluated in Python using `decimal.Decimal`. Floating-point arithmetic is strictly prohibited.
- **Transaction Idempotency:** Enforced via PostgreSQL `UNIQUE` constraint on `transactions.idempotency_key` and application-level payload matching in `BankingService`.
- **Institution Boundaries:** Multitenancy isolation is validated on every request via `X-Institution-ID` headers.
- **Audit Trail Immutability:** State changes atomically create entries in `transaction_status_history` within the same database transaction.
- **Non-Authorization Boundary:** Newly submitted transactions remain in `PENDING_AUTHORIZATION` until explicitly evaluated by the policy engine in future phases.
