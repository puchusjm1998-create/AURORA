"""Slotting and picking-route suggestions computed from real warehouse data."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import RequestMeta, get_request_meta, require_permission
from app.core.db import get_db
from app.core.enums import CalibrationMethod, PermissionCode, ReservationStatus
from app.core.errors import NotFoundError, ValidationError
from app.core.timeutils import utcnow
from app.models import Location, Pallet, Product, RouteTimeSample, StockReservation, User
from app.schemas import (
    CalibrationState,
    CalibrationUpdate,
    PickingRoute,
    PutawayCandidate,
    PutawaySuggestion,
    RouteRequest,
    RouteStop,
    SlottingReport,
    SlottingRow,
    TimeSampleCreate,
    TimeSampleRead,
)
from app.services.audit import record_audit
from app.services.calibration import (
    DEFAULT_CALIBRATION,
    fit_samples,
    load_calibration,
    resolve_warehouse,
    upsert_calibration,
)
from app.services.optimization import (
    NOTE,
    build_route,
    putaway_suggestions,
    slotting_analysis,
)

router = APIRouter(prefix="/optimization", tags=["Optimización"])


def _sample_read(sample: RouteTimeSample) -> TimeSampleRead:
    return TimeSampleRead(
        id=sample.id,
        warehouse_id=sample.warehouse_id,
        warehouse_name=sample.warehouse.name if sample.warehouse else None,
        location_ids=sample.location_ids,
        stops=sample.stops,
        distance_m=sample.distance_m,
        measured_seconds=sample.measured_seconds,
        notes=sample.notes,
        measured_at=sample.measured_at,
        measured_by=sample.measured_by,
        measurer_name=sample.measurer.full_name if sample.measurer else None,
        created_at=sample.created_at,
    )


def _state(db: Session, warehouse_id: str | None, *, fit: dict | None = None) -> CalibrationState:
    warehouse = resolve_warehouse(db, warehouse_id)
    if warehouse_id and warehouse is None:
        raise NotFoundError("Almacén", warehouse_id)
    calibration, meta = load_calibration(db, warehouse.id if warehouse else None)
    samples = (
        list(
            db.scalars(
                select(RouteTimeSample)
                .where(RouteTimeSample.warehouse_id == warehouse.id)
                .order_by(RouteTimeSample.measured_at.desc())
                .limit(25)
            ).all()
        )
        if warehouse
        else []
    )
    total_samples = (
        int(
            db.scalar(
                select(func.count())
                .select_from(RouteTimeSample)
                .where(RouteTimeSample.warehouse_id == warehouse.id)
            )
            or 0
        )
        if warehouse
        else 0
    )
    parameters = {
        "aisle_pitch_m": calibration.aisle_pitch_m,
        "rack_pitch_m": calibration.rack_pitch_m,
        "position_pitch_m": calibration.position_pitch_m,
        "base_pick_seconds": calibration.base_pick_seconds,
        "level_penalty_seconds": calibration.level_penalty_seconds,
        "walking_speed_mps": calibration.walking_speed_mps,
        "setup_seconds": calibration.setup_seconds,
    }
    return CalibrationState(
        warehouse_id=meta["warehouse_id"],
        warehouse_code=meta["warehouse_code"],
        warehouse_name=meta["warehouse_name"],
        parameters=parameters,
        defaults=DEFAULT_CALIBRATION.assumptions(),
        assumptions=calibration.assumptions(),
        method=meta["method"],
        is_default=meta["is_default"],
        sample_count=meta["sample_count"],
        total_samples=total_samples,
        r_squared=meta["r_squared"],
        mae_seconds=meta["mae_seconds"],
        calibrated_at=meta["calibrated_at"],
        calibrated_by=meta["calibrated_by"],
        notes=meta["notes"],
        fit=fit,
        samples=[_sample_read(sample) for sample in samples],
    )


@router.get("/calibration", response_model=CalibrationState, summary="Calibración vigente")
def get_calibration(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
    warehouse_id: str | None = Query(None),
) -> CalibrationState:
    return _state(db, warehouse_id)


@router.put("/calibration", response_model=CalibrationState, summary="Guardar calibración manual")
def update_calibration(
    payload: CalibrationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.LOCATIONS_WRITE)),
    meta_request: RequestMeta = Depends(get_request_meta),
) -> CalibrationState:
    warehouse = resolve_warehouse(db, payload.warehouse_id)
    if warehouse is None:
        raise NotFoundError("Almacén", payload.warehouse_id or "")
    existing_samples = int(
        db.scalar(
            select(func.count())
            .select_from(RouteTimeSample)
            .where(RouteTimeSample.warehouse_id == warehouse.id)
        )
        or 0
    )
    upsert_calibration(
        db,
        warehouse,
        aisle_pitch_m=payload.aisle_pitch_m,
        rack_pitch_m=payload.rack_pitch_m,
        position_pitch_m=payload.position_pitch_m,
        base_pick_seconds=payload.base_pick_seconds,
        level_penalty_seconds=payload.level_penalty_seconds,
        walking_speed_mps=payload.walking_speed_mps,
        setup_seconds=payload.setup_seconds,
        method=CalibrationMethod.MANUAL,
        sample_count=existing_samples,
        r_squared=None,
        mae_seconds=None,
        user_id=user.id,
        notes=payload.notes,
    )
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="calibration.updated",
        entity_type="warehouse",
        entity_id=warehouse.id,
        after={**payload.model_dump(exclude={"warehouse_id"}), "method": "manual"},
        ip=meta_request.ip,
        user_agent=meta_request.user_agent,
    )
    db.commit()
    return _state(db, warehouse.id)


@router.post("/calibration/fit", response_model=CalibrationState, summary="Ajustar con tiempos medidos")
def fit_calibration(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.LOCATIONS_WRITE)),
    meta_request: RequestMeta = Depends(get_request_meta),
    warehouse_id: str | None = Query(None),
) -> CalibrationState:
    warehouse = resolve_warehouse(db, warehouse_id)
    if warehouse is None:
        raise NotFoundError("Almacén", warehouse_id or "")
    samples = list(
        db.scalars(
            select(RouteTimeSample)
            .where(RouteTimeSample.warehouse_id == warehouse.id)
            .order_by(RouteTimeSample.measured_at)
        ).all()
    )
    try:
        fit = fit_samples(samples)
    except ValueError as exc:
        raise ValidationError(str(exc), code="insufficient_samples") from exc
    current, _ = load_calibration(db, warehouse.id)
    upsert_calibration(
        db,
        warehouse,
        aisle_pitch_m=current.aisle_pitch_m,
        rack_pitch_m=current.rack_pitch_m,
        position_pitch_m=current.position_pitch_m,
        base_pick_seconds=fit["base_pick_seconds"],
        level_penalty_seconds=current.level_penalty_seconds,
        walking_speed_mps=fit["walking_speed_mps"],
        setup_seconds=fit["setup_seconds"],
        method=CalibrationMethod.REGRESSION,
        sample_count=fit["sample_count"],
        r_squared=fit["r_squared"],
        mae_seconds=fit["mae_seconds"],
        user_id=user.id,
        notes=f"Ajuste por mínimos cuadrados con {fit['sample_count']} rutas cronometradas.",
    )
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="calibration.fitted",
        entity_type="warehouse",
        entity_id=warehouse.id,
        after=fit,
        ip=meta_request.ip,
        user_agent=meta_request.user_agent,
    )
    db.commit()
    return _state(db, warehouse.id, fit=fit)


@router.post("/time-studies", response_model=TimeSampleRead, status_code=201, summary="Registrar tiempo medido")
def create_time_study(
    payload: TimeSampleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.LOCATIONS_WRITE)),
    meta_request: RequestMeta = Depends(get_request_meta),
) -> TimeSampleRead:
    locations = []
    for location_id in dict.fromkeys(payload.location_ids):
        location = db.get(Location, location_id)
        if location is None:
            raise NotFoundError("Ubicación", location_id)
        locations.append(location)
    warehouse_id = payload.warehouse_id or (locations[0].warehouse_id if locations else None)
    warehouse = resolve_warehouse(db, warehouse_id)
    if warehouse is None:
        raise NotFoundError("Almacén", warehouse_id or "")
    if any(location.warehouse_id != warehouse.id for location in locations):
        raise ValidationError(
            "Todas las ubicaciones deben pertenecer al mismo almacén.", code="mixed_warehouses"
        )
    calibration, _ = load_calibration(db, warehouse.id)
    route = build_route(
        [{"location": location} for location in locations],
        return_to_dispatch=True,
        calibration=calibration,
    )
    sample = RouteTimeSample(
        warehouse_id=warehouse.id,
        location_ids=[location.id for location in locations],
        stops=len(locations),
        distance_m=Decimal(str(route["total_distance_m"])),
        measured_seconds=payload.measured_seconds,
        notes=payload.notes,
        measured_at=payload.measured_at or utcnow(),
        measured_by=user.id,
    )
    db.add(sample)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="time_study.created",
        entity_type="route_time_sample",
        entity_id=sample.id,
        after={
            "warehouse": warehouse.code,
            "stops": sample.stops,
            "distance_m": str(sample.distance_m),
            "measured_seconds": sample.measured_seconds,
        },
        ip=meta_request.ip,
        user_agent=meta_request.user_agent,
    )
    db.commit()
    db.refresh(sample)
    return _sample_read(sample)


@router.delete("/time-studies/{sample_id}", status_code=204, summary="Eliminar tiempo medido")
def delete_time_study(
    sample_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PermissionCode.LOCATIONS_WRITE)),
    meta_request: RequestMeta = Depends(get_request_meta),
) -> Response:
    sample = db.get(RouteTimeSample, sample_id)
    if sample is None:
        raise NotFoundError("Muestra de tiempo", sample_id)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_label=user.full_name,
        action="time_study.deleted",
        entity_type="route_time_sample",
        entity_id=sample.id,
        after={"measured_seconds": sample.measured_seconds, "stops": sample.stops},
        ip=meta_request.ip,
        user_agent=meta_request.user_agent,
    )
    db.delete(sample)
    db.commit()
    return Response(status_code=204)


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
    warehouse_id: str | None = Query(None),
) -> PutawaySuggestion:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("Producto", product_id)
    calibration, calibration_info = load_calibration(db, warehouse_id)
    data = putaway_suggestions(
        db, product, pallets=pallets, limit=limit, calibration=calibration
    )
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
        calibration=calibration_info,
        note=data["note"],
    )


@router.post("/picking-route", response_model=PickingRoute, summary="Ruta de picking sugerida")
def picking_route(
    payload: RouteRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
    warehouse_id: str | None = Query(None),
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

    if warehouse_id is None and stops:
        warehouse_id = stops[0]["location"].warehouse_id
    calibration, calibration_info = load_calibration(db, warehouse_id)
    data = build_route(
        stops,
        return_to_dispatch=payload.return_to_dispatch,
        calibration=calibration,
    )
    return PickingRoute(
        stops=[RouteStop(**stop) for stop in data["stops"]],
        total_distance_m=data["total_distance_m"],
        total_pick_seconds=data["total_pick_seconds"],
        total_walk_seconds=data["total_walk_seconds"],
        total_estimated_seconds=data["total_estimated_seconds"],
        setup_seconds=data["setup_seconds"],
        return_to_dispatch=data["return_to_dispatch"],
        assumptions=data["assumptions"],
        calibration=calibration_info,
        note=NOTE,
    )


@router.get("/slotting", response_model=SlottingReport, summary="Análisis de ubicación de productos")
def slotting(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(25, ge=1, le=100),
    warehouse_id: str | None = Query(None),
) -> SlottingReport:
    calibration, calibration_info = load_calibration(db, warehouse_id)
    data = slotting_analysis(db, days=days, limit=limit, calibration=calibration)
    return SlottingReport(
        days=data["days"],
        total=data["total"],
        items=[SlottingRow(**row) for row in data["items"]],
        assumptions=data["assumptions"],
        calibration=calibration_info,
        note=NOTE,
    )
