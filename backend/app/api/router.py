"""
/api/v1 router. Each later phase mounts its endpoint module here
(tickets/maintenance in B4, parts/notifications/attachments in B5, risk/QA in B6, ...).
"""
from fastapi import APIRouter

from app.api.endpoints import (
    ai, analytics, attachments, auth, catalog, device_history, devices, health, maintenance, notifications, parts,
    qa_records, risk_assessments, structure, tickets, users,
)

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
api_v1_router.include_router(tickets.router)
api_v1_router.include_router(maintenance.router)
api_v1_router.include_router(parts.router)
api_v1_router.include_router(notifications.router)
api_v1_router.include_router(attachments.router)
api_v1_router.include_router(risk_assessments.router)  # B6
api_v1_router.include_router(qa_records.router)  # B6
api_v1_router.include_router(device_history.router)  # B6
api_v1_router.include_router(ai.router)  # B9
api_v1_router.include_router(analytics.router)  # B10
