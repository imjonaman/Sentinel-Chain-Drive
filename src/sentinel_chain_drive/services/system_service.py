"""System service orchestrating health probes, diagnostics, and application metadata."""

import logging

from sqlalchemy.ext.asyncio import AsyncEngine

from sentinel_chain_drive.core.config import get_settings
from sentinel_chain_drive.db.session import check_database_connectivity
from sentinel_chain_drive.schemas.health import (
    DependencyHealth,
    HealthLiveResponse,
    HealthReadyResponse,
)
from sentinel_chain_drive.schemas.system import SystemInfoResponse

logger = logging.getLogger(__name__)


class SystemService:
    """Provides business logic for system health and non-sensitive metadata introspection."""

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self.engine = engine
        self.settings = get_settings()

    def check_liveness(self) -> HealthLiveResponse:
        """Confirm that the application worker process is running and able to handle requests."""
        return HealthLiveResponse(status="ok")

    async def check_readiness(self) -> tuple[HealthReadyResponse, bool]:
        """Verify readiness of all critical external dependencies (such as PostgreSQL).

        Returns:
            (HealthReadyResponse, is_all_healthy)
        """
        db_healthy, latency_ms, error_msg = await check_database_connectivity(
            engine=self.engine,
            timeout_seconds=3.0,
        )

        dependencies: dict[str, DependencyHealth] = {
            "database": DependencyHealth(
                status="healthy" if db_healthy else "unhealthy",
                latency_ms=latency_ms,
                message=None if db_healthy else error_msg,
            )
        }

        overall_ready = db_healthy
        response = HealthReadyResponse(
            status="ready" if overall_ready else "not_ready",
            dependencies=dependencies,
        )
        return response, overall_ready

    def get_system_info(self) -> SystemInfoResponse:
        """Return non-sensitive application identity and environment attributes."""
        return SystemInfoResponse(
            app_name=self.settings.APP_NAME,
            version=self.settings.APP_VERSION,
            environment=self.settings.ENVIRONMENT,
            api_version="v1",
            database_status="configured",
            drunix_adapter_type=self.settings.DRUNIX_ADAPTER_TYPE,
        )
