"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.routes import (
    analytics,
    auth,
    catalog,
    invoices,
    labels,
    movements,
    pallets,
    people,
    reservations,
    system,
    incidents,
    tasks,
    warehouses,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(warehouses.router)
api_router.include_router(catalog.router)
api_router.include_router(pallets.router)
api_router.include_router(movements.router)
api_router.include_router(reservations.router)
api_router.include_router(incidents.router)
api_router.include_router(tasks.router)
api_router.include_router(invoices.router)
api_router.include_router(people.router)
api_router.include_router(analytics.router)
api_router.include_router(labels.router)
