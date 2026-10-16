"""Root router for API version 1."""

from fastapi import APIRouter

from sentinel_chain_drive.api.v1.endpoints import system

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(system.router)

__all__ = ["api_v1_router"]
