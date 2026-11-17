"""Slotting and picking-route suggestions computed from real warehouse data."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.db import get_db
from app.core.enums import PermissionCode, ReservationStatus
from app.core.errors import NotFoundError, ValidationError
from app.models import Location, Pallet, Product, StockReservation, User
from app.schemas import (
    PickingRoute,
    PutawayCandidate,
    PutawaySuggestion,
    RouteRequest,
    RouteStop,
    SlottingReport,
    SlottingRow,
)
from app.services.optimization import (
    ASSUMPTIONS,
    NOTE,
    build_route,
    putaway_suggestions,
    slotting_analysis,
)

router = APIRouter(prefix="/optimization", tags=["Optimización"])


@router.get(
    "/putaway",
    response_model=PutawaySuggestion,
    summary="Sugerencia de ubicación para una entrada",
)
def putaway(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
    product_id: str = Query(...),
    pallets: int = Query(1, ge=1, le=200),
    limit: int = Query(5, ge=1, le=20),
) -> PutawaySuggestion:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("Producto", product_id)
    data = putaway_suggestions(db, product, pallets=pallets, limit=limit)
    return PutawaySuggestion(
        product_id=product.id,
        product_sku=product.sku,
        product_name=product.name,
        pallets=data["pallets"],
        fast_mover=data["fast_mover"],
        moves=data["moves"],
        fits=data["fits"],
        candidates=[
            PutawayCandidate(
                location_id=item["location"].id,
                location_code=item["location"].full_code,
                is_pick_face=item["location"].is_pick_face,
                capacity_pallets=item["location"].capacity_pallets,
                occupied_pallets=item["occupied_pallets"],
                free_pallets=item["free_pallets"],
                units=item["units"],
                same_product_units=item["same_product_units"],
                distance_m=item["distance_m"],
                score=item["score"],
                reasons=item["reasons"],
            )
            for item in data["candidates"]
        ],
        assumptions=data["assumptions"],
        note=data["note"],
    )


@router.post("/picking-route", response_model=PickingRoute, summary="Ruta de picking sugerida")
def picking_route(
    payload: RouteRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> PickingRoute:
    has_reference = bool(payload.reservation_reference and payload.reservation_reference.strip())
    has_locations = bool(payload.location_ids)
    if has_reference == has_locations:
        raise ValidationError(
            "Indique una referencia de reserva o una lista de ubicaciones (solo una de las dos).",
            code="route_source_required",
        )

    stops: list[dict] = []
    if has_reference:
        reference = (payload.reservation_reference or "").strip()
        reservations = list(
            db.scalars(
                select(StockReservation).where(
                    StockReservation.reference == reference,
                    StockReservation.status == ReservationStatus.ACTIVE,
                )
            ).all()
        )
        if not reservations:
            raise NotFoundError("Reserva activa", reference)
        pallet_ids = {reservation.pallet_id for reservation in reservations if reservation.pallet_id}
        pallets = {
            pallet.id: pallet
            for pallet in db.scalars(select(Pallet).where(Pallet.id.in_(pallet_ids))).all()
        } if pallet_ids else {}
        grouped: dict[tuple[str, str, str | None], dict] = {}
        for reservation in reservations:
            key = (reservation.location_id, reservation.product_id, reservation.pallet_id)
            entry = grouped.setdefault(
                key,
                {
                    "location": reservation.location,
                    "product_id": reservation.product_id,
                    "product_sku": reservation.product.sku if reservation.product else None,
                    "product_name": reservation.product.name if reservation.product else None,
                    "quantity": Decimal("0"),
                    "pallet_code": pallets[reservation.pallet_id].code
                    if reservation.pallet_id and reservation.pallet_id in pallets
                    else None,
                },
            )
            entry["quantity"] += reservation.quantity
        stops = list(grouped.values())
    else:
        seen: set[str] = set()
        for location_id in payload.location_ids:
            if location_id in seen:
                continue
            seen.add(location_id)
            location = db.get(Location, location_id)
            if location is None:
                raise NotFoundError("Ubicación", location_id)
            stops.append({"location": location})

    data = build_route(stops, return_to_dispatch=payload.return_to_dispatch)
    return PickingRoute(
        stops=[RouteStop(**stop) for stop in data["stops"]],
        total_distance_m=data["total_distance_m"],
        total_pick_seconds=data["total_pick_seconds"],
        return_to_dispatch=data["return_to_dispatch"],
        assumptions=ASSUMPTIONS,
        note=NOTE,
    )


@router.get("/slotting", response_model=SlottingReport, summary="Análisis de ubicación de productos")
def slotting(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(25, ge=1, le=100),
) -> SlottingReport:
    data = slotting_analysis(db, days=days, limit=limit)
    return SlottingReport(
        days=data["days"],
        total=data["total"],
        items=[SlottingRow(**row) for row in data["items"]],
        assumptions=ASSUMPTIONS,
        note=NOTE,
    )
