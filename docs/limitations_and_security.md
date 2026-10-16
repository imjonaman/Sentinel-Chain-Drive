# Sentinel Chain Drive - Known Limitations and Security Assumptions

## 1. Security Principles & Controls Implemented

1. **Deny Access by Default**:
   - The platform rejects unauthorized actions by default.
   - CORS is configured conservatively; wildcards (`*`) are disallowed and raise configuration errors.

2. **No Trust in Client-Supplied Roles or Identities**:
   - Authentication and authorization will never trust client-supplied user, role, or agent fields.

3. **Information Shielding (No Leakage in API Errors)**:
   - Unhandled exceptions return generic messages (`500 INTERNAL_SERVER_ERROR`) with a traceable `correlation_id`.
   - Internal paths, database URLs, credentials, and full stack traces are strictly suppressed from all API responses.

4. **Credential Protection & Sanitized Logging**:
   - Database passwords use Pydantic `SecretStr` and are masked in representation and serialization.
   - Structured logging filter automatically inspects log arguments and redacts fields matching sensitive patterns (`password`, `token`, `secret`, `authorization`, `private_key`, `api_key`).

5. **Parameterized Persistence**:
   - All database interaction passes through SQLAlchemy 2.x parameterized expressions, mitigating SQL injection risks.

6. **Defensive HTTP Headers**:
   - Outbound responses include `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Content-Security-Policy: default-src 'self'`.

7. **DoS Prevention (Request Size Limits)**:
   - Requests with bodies exceeding the configured maximum size (default 1 MB) are rejected immediately with HTTP 413.

---

## 2. Phase 1 Known Limitations

1. **No Real Banking or Ledger Connectivity**:
   - In accordance with Phase 1 constraints, Sentinel Chain Drive does not connect to real bank cores, payment rails (FedNow, SWIFT, SEPA), or live DRUNIX blockchain nodes.
   - The `DRUNIXAdapter` implementation is currently an in-memory `MockDRUNIXAdapter`.

2. **Authorization & Graph Analysis Logic Deferred**:
   - Specific AgentID capability rules (allow/step-up/hold/decline policies) and MuleChain cross-bank graph analytics are planned for subsequent phases and are intentionally not implemented as fake or unenforced placeholders in Phase 1.

3. **Single Datastore Boundary**:
   - PostgreSQL is the sole authoritative operational store. Distributed message brokers (Kafka/RabbitMQ) and cache tiers (Redis) have not been introduced during Phase 1.

4. **Local Host Docker Dependency**:
   - While `docker-compose.yml` and `Dockerfile` are provided, the local Windows development host may not have the Docker daemon installed. Direct virtual environment execution (`uvicorn`) and standalone SQLite testing fixtures are provided as a verified fallback.

---

## 3. Security Assumptions & Operational Boundaries

1. **TLS / HTTPS Termination**:
   - Production deployments assume TLS termination is handled by an edge proxy, ingress controller, or API gateway (e.g., NGINX, Cloudflare, Traefik). Application communication within the internal network must be secured or encrypted.

2. **Secrets Injection**:
   - Production secrets (e.g., database credentials, future cryptographic keys) must be injected via secure environment variables or a secret management service (such as HashiCorp Vault, AWS Secrets Manager, or GCP Secret Manager), never committed to source files.

3. **Network Isolation**:
   - Direct database port access should be restricted to the application network segment.

4. **Regulatory and Compliance Notice**:
   - Successful automated test execution in Phase 1 provides foundational verification but does not constitute formal regulatory compliance (e.g., PCI-DSS, SOC 2, ISO 27001) or production readiness.
