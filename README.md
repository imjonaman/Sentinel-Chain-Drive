# Sentinel Chain Drive

**AI-Agent Authorization and Cross-Bank Fraud Intelligence Platform**

Sentinel Chain Drive is an enterprise security and intelligence platform designed to govern autonomous AI-agent financial transactions and detect cross-institution fraud networks. The platform couples deterministic policy evaluation and AI capability bounds with privacy-preserving cross-bank transaction graph analytics.

---

## Current Status: Phase 2 Complete

- **Phase 1 (Foundation):** Completed. Enterprise FastAPI framework, structured JSON logging with correlation IDs, database connection pooling, Alembic migration framework, standardized error taxonomy, and RFC 7807 problem details.
- **Phase 2 (Simulated Banking Environment & Transaction Domain):** Completed. Multi-institution simulated banking domain, account management with lifecycle constraints, transaction domain with strict decimal precision, idempotent transaction gateway, audit trail state history, synthetic seed fixtures, and tenant boundary enforcement.
- **Phase 3 (AgentID & Capability Registry):** Next phase.

---

## Phase 2 Architectural Capabilities

### 1. Multi-Institution Management
- Manage simulated banking institutions (`ACTIVE`, `SUSPENDED`, `INACTIVE`).
- Validated state transition rules preventing illegal activation/deactivation cycles.
- Unique BIC/SWIFT-compliant institution codes and routing identifiers.
- Metadata and operational settings management.

### 2. Account Management
- Synthetic account provisioning associated with registered institutions.
- Multi-currency support (e.g., `USD`, `EUR`, `GBP`) with normalized uppercase ISO codes.
- Account status lifecycle (`ACTIVE`, `FROZEN`, `CLOSED`) with terminal closed states.
- Non-negative balance constraints enforced at the database level (`Numeric(18, 4)`).
- Risk flags and institution ownership isolation.

### 3. Transaction Domain & State Machine
- **Strict Monetary Safety:** All financial amounts use `Decimal` with fixed-scale numeric types (`Numeric(18, 4)`). Binary floating-point arithmetic is strictly prohibited.
- **Controlled Lifecycle:** Transactions follow a state machine:
  `SUBMITTED` &rarr; `PENDING_AUTHORIZATION` &rarr; `HELD` | `SETTLED` | `REJECTED` | `CANCELLED`.
- **Non-Authorization Invariant:** Newly submitted transactions enter `PENDING_AUTHORIZATION`. The simulation gateway never auto-approves or settles transactions upon submission; execution requires explicit authorization (orchestrated in Phase 3).
- **Atomic State Transitions & Audit Trail:** Every status change is atomically recorded in `transaction_status_history` capturing `previous_status`, `new_status`, `reason`, `actor`, and `correlation_id`.

### 4. Idempotency & Gateway Resilience
- Database-backed unique constraints on `idempotency_key`.
- Deterministic idempotency handling:
  - Exact payload replay returns `HTTP 200 OK` with the existing transaction resource.
  - Conflicting payload with a reused idempotency key returns `HTTP 409 Conflict`.
- Institution-level tenant boundaries enforced via optional `X-Institution-ID` headers.

### 5. Deterministic Synthetic Seeding
- Repeatable, fully synthetic seed generator creating:
  - 4 Institutions (Apex Commercial, Beacon Trust, Crestline Reserve, Dormant Regional).
  - 7 Accounts across checking, savings, operational, and settlement types.
  - 4 Transactions exercising the full lifecycle and audit history.
- Zero customer PII or production banking credentials.

---

## Technology Stack

- **Language:** Python 3.13+
- **Framework:** FastAPI, Pydantic v2, Pydantic-Settings
- **ORM & Database:** SQLAlchemy 2.x (asyncio), PostgreSQL 16 / asyncpg / psycopg
- **Migrations:** Alembic
- **Testing:** pytest, pytest-asyncio, HTTPX
- **Quality Assurance:** Ruff (linter/formatter), mypy (strict type checker)
- **Containerization:** Docker & Docker Compose

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

---

## Verification & Testing

### Running Tests
Execute the automated test suite with pytest:
```powershell
pytest
```
*Expected: 40 tests passed (17 Phase 1 regression tests + 23 Phase 2 unit & integration tests).*

### Code Quality & Static Analysis
```powershell
# Check code formatting (Ruff)
ruff format --check .

# Run linter checks (Ruff)
ruff check .

# Run strict static type verification (mypy)
mypy src tests
```

---

## Security Invariants & Limitations

1. **Simulated Environment:** All accounts, routing numbers, and balances are strictly synthetic. No real-world banking networks (Fedwire, SWIFT, ACH) or customer credentials are used.
2. **Deterministic Financial Math:** Amounts are stored as exact scale decimals (`Numeric(18, 4)`) and serialized as string representations to avoid floating-point loss in JSON.
3. **No Premature Settlement:** Submissions do not automatically execute. Authorization decisions are reserved for the Phase 3 Policy Engine.
4. **Tenant Isolation:** Multi-tenancy boundaries are verified via `X-Institution-ID` headers to prevent cross-institution data leakage.
