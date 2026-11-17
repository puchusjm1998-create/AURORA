"""Slotting and picking-route suggestions.

Everything here is a *suggestion* computed from real data: nothing is moved
automatically. The geometric model is deliberately simple and explicit, because
the database stores aisle/rack/level/position codes but not metres. The same
assumptions are returned with every response so the estimate can be audited:

* distance between aisle centres: 3.0 m
* distance between racks inside an aisle: 6.0 m
* distance between positions: 1.0 m
* base picking time per stop: 25 s, plus 6 s for each level above the first

Dispatch is the origin (0, 0). Routes use an S-shape sweep: aisles are visited
in ascending order and positions alternate direction to avoid walking back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import OUTBOUND_TYPES, MovementStatus
from app.core.timeutils import utcnow
from app.models import Location, Product, StockLevel, StockMovement

AISLE_PITCH_M = 3.0
RACK_PITCH_M = 6.0
POSITION_PITCH_M = 1.0
BASE_PICK_SECONDS = 25
LEVEL_PENALTY_SECONDS = 6

ASSUMPTIONS: dict[str, float] = {
    "aisle_pitch_m": AISLE_PITCH_M,
    "rack_pitch_m": RACK_PITCH_M,
    "position_pitch_m": POSITION_PITCH_M,
    "base_pick_seconds": BASE_PICK_SECONDS,
    "level_penalty_seconds": LEVEL_PENALTY_SECONDS,
}

NOTE = (
    "Estimación calculada con un modelo geométrico simplificado del almacén. "
    "No se mueve ni reserva stock: la decisión y el movimiento son del usuario."
)

_DIGITS = re.compile(r"(\d+)")


def _number(value: str | None, fallback: int = 1) -> int:
    if not value:
        return fallback
    match = _DIGITS.search(value)
    return int(match.group(1)) if match else fallback


@dataclass(frozen=True)
class Coordinates:
    x: float
    y: float
    aisle: int
    level: int


def coordinates(location: Location) -> Coordinates:
    aisle = max(1, _number(location.aisle, 1))
    rack = max(1, _number(location.rack, 1))
    level = max(1, _number(location.level, 1))
    position = max(1, _number(location.position, 1))
    return Coordinates(
        x=(aisle - 1) * AISLE_PITCH_M,
        y=(rack - 1) * RACK_PITCH_M + (position - 1) * POSITION_PITCH_M,
        aisle=aisle,
        level=level,
    )


def distance(a: Coordinates, b: Coordinates) -> float:
    return abs(a.x - b.x) + abs(a.y - b.y)


DISPATCH = Coordinates(x=0.0, y=0.0, aisle=0, level=1)


def _occupied_pallets(db: Session, location_ids: Sequence[str]) -> dict[str, tuple[int, Decimal, set[str]]]:
    """Return per location: occupied pallets, units, product ids present."""
    result: dict[str, tuple[int, Decimal, set[str]]] = {}
    if not location_ids:
        return result
    rows = db.execute(
        select(
            StockLevel.location_id,
            StockLevel.pallet_id,
            StockLevel.product_id,
            func.sum(StockLevel.quantity),
        )
        .where(StockLevel.location_id.in_(location_ids), StockLevel.quantity > 0)
        .group_by(StockLevel.location_id, StockLevel.pallet_id, StockLevel.product_id)
    ).all()
    pallets: dict[str, set[str]] = {}
    loose: dict[str, bool] = {}
    units: dict[str, Decimal] = {}
    products: dict[str, set[str]] = {}
    for location_id, pallet_id, product_id, quantity in rows:
        if pallet_id:
            pallets.setdefault(location_id, set()).add(pallet_id)
        else:
            loose[location_id] = True
        units[location_id] = units.get(location_id, Decimal("0")) + Decimal(str(quantity or 0))
        products.setdefault(location_id, set()).add(product_id)
    for location_id in set(pallets) | set(loose) | set(units):
        occupied = len(pallets.get(location_id, set())) + (1 if loose.get(location_id) else 0)
        result[location_id] = (occupied, units.get(location_id, Decimal("0")), products.get(location_id, set()))
    return result


def _moves(db: Session, product_id: str, days: int) -> int:
    since = utcnow() - timedelta(days=days)
    return int(
        db.scalar(
            select(func.count(StockMovement.id)).where(
                StockMovement.product_id == product_id,
                StockMovement.status == MovementStatus.CONFIRMED,
                StockMovement.movement_type.in_([t.value for t in OUTBOUND_TYPES]),
                StockMovement.created_at >= since,
            )
        )
        or 0
    )


def putaway_suggestions(
    db: Session,
    product: Product,
    *,
    pallets: int = 1,
    limit: int = 5,
    window_days: int = 30,
) -> dict:
    moves = _moves(db, product.id, window_days)
    fast_mover = moves >= 3
    locations = list(
        db.scalars(
            select(Location)
            .where(Location.is_active.is_(True), Location.capacity_pallets > 0)
            .order_by(Location.full_code)
        ).all()
    )
    occupancy = _occupied_pallets(db, [location.id for location in locations])

    candidates: list[dict] = []
    for location in locations:
        occupied, units, products = occupancy.get(location.id, (0, Decimal("0"), set()))
        free = max(location.capacity_pallets - occupied, 0)
        if free <= 0:
            continue
        coords = coordinates(location)
        dist = distance(coords, DISPATCH)
        score = 40.0
        reasons: list[str] = []

        if product.id in products:
            score += 45
            reasons.append("Ya almacena este producto: consolida la recogida (+45)")
        if location.is_pick_face:
            if fast_mover:
                score += 20
                reasons.append(f"Cara de picking y producto de alta rotación ({moves} salidas) (+20)")
            else:
                score -= 12
                reasons.append("Cara de picking reservada a productos de alta rotación (-12)")
        if occupied > 0:
            score += 10
            reasons.append("Ubicación parcialmente ocupada: aprovecha el hueco (+10)")
        else:
            reasons.append("Ubicación vacía (+0)")
        if coords.level <= 1:
            score += 4
            reasons.append("Nivel bajo: menos tiempo de manipulación (+4)")
        elif coords.level >= 3:
            score -= 5
            reasons.append("Nivel alto: penalización de manipulación (-5)")
        if fast_mover:
            score += max(0.0, 15.0 - dist)
            if dist <= 15:
                reasons.append(f"Cerca del muelle de salida ({dist:.1f} m) (+{max(0.0, 15.0 - dist):.0f})")
        else:
            score += min(8.0, dist / 12.0)
            if dist >= 30:
                reasons.append("Producto de baja rotación: ocupa posiciones alejadas del muelle (+8)")

        candidates.append(
            {
                "location": location,
                "occupied_pallets": occupied,
                "free_pallets": free,
                "units": units,
                "same_product_units": units if product.id in products else Decimal("0"),
                "distance_m": dist,
                "score": round(max(0.0, min(100.0, score)), 1),
                "reasons": reasons,
            }
        )

    fits = [candidate for candidate in candidates if candidate["free_pallets"] >= pallets]
    ranked = sorted(
        fits if fits else candidates,
        key=lambda item: (item["score"], item["free_pallets"]),
        reverse=True,
    )[:limit]
    return {
        "product": product,
        "pallets": pallets,
        "moves": moves,
        "fast_mover": fast_mover,
        "window_days": window_days,
        "candidates": ranked,
        "fits": bool(fits),
        "assumptions": ASSUMPTIONS,
        "note": NOTE,
    }


def build_route(stops: Iterable[dict], *, return_to_dispatch: bool = True) -> dict:
    """Order stops with an S-shape sweep and compute walking/pick estimates."""
    prepared = []
    for stop in stops:
        location: Location = stop["location"]
        coords = coordinates(location)
        prepared.append({**stop, "coords": coords})

    by_aisle: dict[int, list[dict]] = {}
    for stop in prepared:
        by_aisle.setdefault(stop["coords"].aisle, []).append(stop)

    ordered: list[dict] = []
    for index, aisle in enumerate(sorted(by_aisle)):
        aisle_stops = sorted(by_aisle[aisle], key=lambda item: item["coords"].y, reverse=index % 2 == 1)
        ordered.extend(aisle_stops)

    previous = DISPATCH
    total_distance = 0.0
    total_seconds = 0
    result_stops = []
    for sequence, stop in enumerate(ordered, start=1):
        coords: Coordinates = stop["coords"]
        leg = distance(previous, coords)
        total_distance += leg
        pick_seconds = BASE_PICK_SECONDS + LEVEL_PENALTY_SECONDS * (coords.level - 1)
        total_seconds += pick_seconds
        location: Location = stop["location"]
        result_stops.append(
            {
                "sequence": sequence,
                "location_id": location.id,
                "location_code": location.full_code,
                "product_id": stop.get("product_id"),
                "product_sku": stop.get("product_sku"),
                "product_name": stop.get("product_name"),
                "quantity": stop.get("quantity"),
                "pallet_code": stop.get("pallet_code"),
                "distance_from_previous_m": round(leg, 1),
                "pick_seconds": pick_seconds,
            }
        )
        previous = coords

    if return_to_dispatch and ordered:
        total_distance += distance(previous, DISPATCH)

    return {
        "stops": result_stops,
        "total_distance_m": round(total_distance, 1),
        "total_pick_seconds": total_seconds,
        "return_to_dispatch": return_to_dispatch,
        "assumptions": ASSUMPTIONS,
        "note": NOTE,
    }


def slotting_analysis(db: Session, *, days: int = 30, limit: int = 25) -> dict:
    since = utcnow() - timedelta(days=days)
    movement_rows = db.execute(
        select(
            StockMovement.product_id,
            func.count(StockMovement.id),
            func.coalesce(func.sum(StockMovement.quantity), 0),
        )
        .where(
            StockMovement.status == MovementStatus.CONFIRMED,
            StockMovement.movement_type.in_([t.value for t in OUTBOUND_TYPES]),
            StockMovement.created_at >= since,
        )
        .group_by(StockMovement.product_id)
    ).all()
    movements = {
        product_id: (int(count), Decimal(str(units or 0)))
        for product_id, count, units in movement_rows
    }

    stock_rows = db.execute(
        select(StockLevel.product_id, StockLevel.location_id, func.sum(StockLevel.quantity))
        .where(StockLevel.quantity > 0)
        .group_by(StockLevel.product_id, StockLevel.location_id)
    ).all()
    locations_by_id = {
        location.id: location for location in db.scalars(select(Location)).all()
    }
    product_locations: dict[str, list[tuple[Location, Decimal]]] = {}
    for product_id, location_id, quantity in stock_rows:
        location = locations_by_id.get(location_id)
        if location is None:
            continue
        product_locations.setdefault(product_id, []).append((location, Decimal(str(quantity or 0))))

    products = {
        product.id: product
        for product in db.scalars(select(Product).where(Product.is_active.is_(True))).all()
    }

    rows = []
    for product_id, product in products.items():
        count, units_out = movements.get(product_id, (0, Decimal("0")))
        locations = product_locations.get(product_id, [])
        if not locations and count == 0:
            continue
        pick_face = any(location.is_pick_face for location, _ in locations)
        nearest = min((distance(coordinates(location), DISPATCH) for location, _ in locations), default=None)
        recommendation = "Mantener ubicación actual"
        reason = "Sin cambios necesarios con los datos actuales."
        if count >= 3 and not pick_face:
            recommendation = "Mover a cara de picking"
            reason = f"{count} salidas en {days} días y ninguna posición de picking."
        elif count == 0 and pick_face:
            recommendation = "Liberar cara de picking"
            reason = f"Sin salidas en {days} días ocupando una posición preferente."
        elif len(locations) >= 3:
            recommendation = "Consolidar ubicaciones"
            reason = f"El producto está disperso en {len(locations)} posiciones."
        elif count >= 3 and nearest is not None and nearest > 30:
            recommendation = "Acercar al muelle"
            reason = f"Producto de alta rotación a {nearest:.1f} m del muelle."
        rows.append(
            {
                "product_id": product_id,
                "product_sku": product.sku,
                "product_name": product.name,
                "moves": count,
                "units_out": units_out,
                "locations": len(locations),
                "in_pick_face": pick_face,
                "nearest_distance_m": round(nearest, 1) if nearest is not None else None,
                "on_hand": sum((quantity for _, quantity in locations), Decimal("0")),
                "recommendation": recommendation,
                "reason": reason,
            }
        )

    rows.sort(key=lambda item: (item["moves"], item["on_hand"]), reverse=True)
    return {
        "days": days,
        "items": rows[:limit],
        "total": len(rows),
        "assumptions": ASSUMPTIONS,
        "note": NOTE,
    }
