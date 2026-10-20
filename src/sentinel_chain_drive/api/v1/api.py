"""Root router for API version 1."""

from fastapi import APIRouter

from sentinel_chain_drive.api.v1.endpoints import (
    accounts,
    agents,
    capabilities,
    credentials,
    institutions,
    mulechain,
    policies,
    privacy,
    system,
    transactions,
)

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(system.router)
api_v1_router.include_router(institutions.router)
api_v1_router.include_router(accounts.router)
api_v1_router.include_router(transactions.router)
api_v1_router.include_router(agents.router)
api_v1_router.include_router(capabilities.router)
api_v1_router.include_router(credentials.credentials_router)
api_v1_router.include_router(credentials.authorizations_router)
api_v1_router.include_router(policies.router)
api_v1_router.include_router(mulechain.router)
api_v1_router.include_router(privacy.router)

__all__ = ["api_v1_router"]

