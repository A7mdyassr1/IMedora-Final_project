"""
/api/v1 router. Each later phase mounts its endpoint module here
(auth in B2, devices in B3, ...). Only health is mounted so far.
"""
from fastapi import APIRouter

from app.api.endpoints import health

api_v1_router = APIRouter()

# Also reachable as /api/v1/health for clients that only know the versioned
# prefix. Hidden from the OpenAPI schema so /health isn't documented twice.
api_v1_router.include_router(health.router, include_in_schema=False)
