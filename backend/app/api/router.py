"""
/api/v1 router. Each later phase mounts its endpoint module here
(devices in B3, tickets in B4, ...).
"""
from fastapi import APIRouter

from app.api.endpoints import auth, health, users

api_v1_router = APIRouter()

# Also reachable as /api/v1/health for clients that only know the versioned
# prefix. Hidden from the OpenAPI schema so /health isn't documented twice.
api_v1_router.include_router(health.router, include_in_schema=False)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(users.router)
