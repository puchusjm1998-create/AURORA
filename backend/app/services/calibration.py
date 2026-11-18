"""Calibración del modelo de rutas con el plano y tiempos medidos del almacén."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import CalibrationMethod
from app.models import RouteTimeSample, Warehouse, WarehouseCalibration


@dataclass(frozen=True)
class Calibration:
    aisle_pitch_m: float = 3.0
    rack_pitch_m: float = 6.0
    position_pitch_m: float = 1.0
    base_pick_seconds: float = 25.0
    level_penalty_seconds: float = 6.0
    walking_speed_mps: float = 1.0
    setup_seconds: float = 0.0

    def assumptions(self) -> dict[str, float]:
        return {
            "aisle_pitch_m": round(self.aisle_pitch_m, 2),
            "rack_pitch_m": round(self.rack_pitch_m, 2),
            "position_pitch_m": round(self.position_pitch_m, 2),
            "base_pick_seconds": round(self.base_pick_seconds, 2),
            "level_penalty_seconds": round(self.level_penalty_seconds, 2),
            "walking_speed_mps": round(self.walking_speed_mps, 2),
            "setup_seconds": round(self.setup_seconds, 2),
        }

    def walk_seconds(self, distance_m: float) -> float:
        return distance_m / max(self.walking_speed_mps, 0.1)


DEFAULT_CALIBRATION = Calibration()


def resolve_warehouse(db: Session, warehouse_id: str | None = None) -> Warehouse | None:
    if warehouse_id:
        return db.get(Warehouse, warehouse_id)
    return db.scalars(
        select(Warehouse).where(Warehouse.is_active.is_(True)).order_by(Warehouse.code)
    ).first() or db.scalars(select(Warehouse).order_by(Warehouse.code)).first()


def calibration_meta(
    warehouse: Warehouse | None, row: WarehouseCalibration | None
) -> dict[str, Any]:
    if warehouse is None:
        return {
            "warehouse_id": None,
            "warehouse_code": None,
            "warehouse_name": None,
            "method": "default",
            "is_default": True,
            "sample_count": 0,
            "r_squared": None,
            "mae_seconds": None,
            "calibrated_at": None,
            "calibrated_by": None,
            "notes": "",
        }
    return {
        "warehouse_id": warehouse.id,
        "warehouse_code": warehouse.code,
        "warehouse_name": warehouse.name,
        "method": row.method.value if row else "default",
        "is_default": row is None,
        "sample_count": row.sample_count if row else 0,
        "r_squared": float(row.r_squared) if row and row.r_squared is not None else None,
        "mae_seconds": float(row.mae_seconds) if row and row.mae_seconds is not None else None,
        "calibrated_at": row.calibrated_at.isoformat() if row else None,
        "calibrated_by": row.calibrator.full_name if row and row.calibrator else None,
        "notes": row.notes if row else "",
    }


def load_calibration(
    db: Session, warehouse_id: str | None = None
) -> tuple[Calibration, dict[str, Any]]:
    warehouse = resolve_warehouse(db, warehouse_id)
    if warehouse is None:
        return DEFAULT_CALIBRATION, calibration_meta(None, None)
    row = db.scalars(
        select(WarehouseCalibration).where(WarehouseCalibration.warehouse_id == warehouse.id)
    ).first()
    if row is None:
        return DEFAULT_CALIBRATION, calibration_meta(warehouse, None)
    calibration = Calibration(
        aisle_pitch_m=float(row.aisle_pitch_m),
        rack_pitch_m=float(row.rack_pitch_m),
        position_pitch_m=float(row.position_pitch_m),
        base_pick_seconds=float(row.base_pick_seconds),
        level_penalty_seconds=float(row.level_penalty_seconds),
        walking_speed_mps=float(row.walking_speed_mps),
        setup_seconds=float(row.setup_seconds),
    )
    return calibration, calibration_meta(warehouse, row)


def fit_samples(samples: list[RouteTimeSample]) -> dict[str, Any]:
    """Ajusta tiempo = intercepto + distancia/velocidad + paradas*tiempo_parada.

    Con menos de 3 muestras no hay grados de libertad suficientes: se rechaza en
    lugar de inventar una calibración.
    """
    if len(samples) < 3:
        raise ValueError("Se necesitan al menos 3 rutas cronometradas para ajustar el modelo.")
    distances = np.array([float(sample.distance_m) for sample in samples], dtype=float)
    stops = np.array([float(sample.stops) for sample in samples], dtype=float)
    measured = np.array([float(sample.measured_seconds) for sample in samples], dtype=float)
    if float(np.ptp(distances)) < 0.01:
        raise ValueError("Las rutas medidas deben tener distancias diferentes.")

    design = np.column_stack([np.ones(len(samples)), distances, stops])
    coefficients, *_ = np.linalg.lstsq(design, measured, rcond=None)
    intercept, distance_coefficient, stop_coefficient = (float(value) for value in coefficients)

    speed = min(max(1.0 / max(distance_coefficient, 1e-6), 0.2), 3.0)
    base_pick = min(max(stop_coefficient, 1.0), 600.0)
    setup = min(max(intercept, 0.0), 3600.0)

    predicted = setup + distances / speed + stops * base_pick
    residuals = measured - predicted
    sse = float(np.sum(residuals**2))
    sst = float(np.sum((measured - float(np.mean(measured))) ** 2))
    r_squared = 1.0 - sse / sst if sst > 0 else 0.0
    mae = float(np.mean(np.abs(residuals)))
    return {
        "walking_speed_mps": round(speed, 2),
        "base_pick_seconds": round(base_pick, 2),
        "setup_seconds": round(setup, 2),
        "r_squared": round(max(min(r_squared, 1.0), -1.0), 4),
        "mae_seconds": round(mae, 2),
        "sample_count": len(samples),
        "raw_coefficients": {
            "intercept": round(intercept, 4),
            "per_metre": round(distance_coefficient, 4),
            "per_stop": round(stop_coefficient, 4),
        },
    }


def upsert_calibration(
    db: Session,
    warehouse: Warehouse,
    *,
    aisle_pitch_m: Decimal | float,
    rack_pitch_m: Decimal | float,
    position_pitch_m: Decimal | float,
    base_pick_seconds: Decimal | float,
    level_penalty_seconds: Decimal | float,
    walking_speed_mps: Decimal | float,
    setup_seconds: Decimal | float,
    method: CalibrationMethod,
    sample_count: int,
    r_squared: float | None,
    mae_seconds: float | None,
    user_id: str | None,
    notes: str = "",
    calibrated_at: datetime | None = None,
) -> WarehouseCalibration:
    from app.core.timeutils import utcnow

    row = db.scalars(
        select(WarehouseCalibration).where(WarehouseCalibration.warehouse_id == warehouse.id)
    ).first()
    if row is None:
        row = WarehouseCalibration(warehouse_id=warehouse.id)
        db.add(row)
    row.aisle_pitch_m = Decimal(str(aisle_pitch_m))
    row.rack_pitch_m = Decimal(str(rack_pitch_m))
    row.position_pitch_m = Decimal(str(position_pitch_m))
    row.base_pick_seconds = Decimal(str(base_pick_seconds))
    row.level_penalty_seconds = Decimal(str(level_penalty_seconds))
    row.walking_speed_mps = Decimal(str(walking_speed_mps))
    row.setup_seconds = Decimal(str(setup_seconds))
    row.method = method
    row.sample_count = sample_count
    row.r_squared = Decimal(str(r_squared)) if r_squared is not None else None
    row.mae_seconds = Decimal(str(mae_seconds)) if mae_seconds is not None else None
    row.calibrated_at = calibrated_at or utcnow()
    row.calibrated_by = user_id
    row.notes = notes
    db.flush()
    return row
