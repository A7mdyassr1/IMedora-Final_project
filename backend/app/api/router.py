"""
/api/v1 router. Each later phase mounts its endpoint module here
(tickets/maintenance in B4, ...).
"""
from fastapi import APIRouter

from app.api.endpoints import auth, catalog, devices, health, structure, users

api_v1_router = APIRouter()

# Also reachable as /api/v1/health for clients that only know the versioned
# prefix. Hidden from the OpenAPI schema so /health isn't documented twice.
api_v1_router.include_router(health.router, include_in_schema=False)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(users.router)
api_v1_router.include_router(structure.org_router)
api_v1_router.include_router(structure.hospital_router)
api_v1_router.include_router(structure.department_router)
api_v1_router.include_router(structure.location_router)
api_v1_router.include_router(catalog.category_router)
api_v1_router.include_router(catalog.manufacturer_router)
api_v1_router.include_router(catalog.model_router)
api_v1_router.include_router(devices.router)
