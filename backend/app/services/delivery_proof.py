"""Prueba de entrega: GPS y firma del receptor.

Los puntos GPS y la firma son evidencias append-only. La distancia se calcula
con la fórmula de Haversine y descarta saltos incompatibles con un vehículo
(> 55 m/s) o puntos con precisión declarada peor que 500 m, para que un error
del navegador no invente kilómetros.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime

from app.core.timeutils import ensure_utc, utcnow
from app.models import DeliverySignature, DeliveryTracking
from app.schemas import DeliveryTrackingRead, DeliveryTrackingSummary
from app.services.storage import resolve_stored_path

STALE_AFTER_SECONDS = 180
MAX_SEGMENT_METERS = 5000.0
MAX_SPEED_MPS = 55.0
MAX_ACCURACY_M = 500.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def point_to_read(point: DeliveryTracking) -> DeliveryTrackingRead:
    return DeliveryTrackingRead(
        id=point.id,
        latitude=float(point.latitude),
        longitude=float(point.longitude),
        accuracy_m=float(point.accuracy_m) if point.accuracy_m is not None else None,
        speed_mps=float(point.speed_mps) if point.speed_mps is not None else None,
        heading_deg=float(point.heading_deg) if point.heading_deg is not None else None,
        source=point.source,
        recorded_at=point.recorded_at,
        recorded_by=point.creator.full_name if point.creator else None,
    )


def _segment_is_plausible(previous: DeliveryTracking, current: DeliveryTracking) -> bool:
    if previous.accuracy_m is not None and float(previous.accuracy_m) > MAX_ACCURACY_M:
        return False
    if current.accuracy_m is not None and float(current.accuracy_m) > MAX_ACCURACY_M:
        return False
    start = ensure_utc(previous.recorded_at)
    end = ensure_utc(current.recorded_at)
    if start is None or end is None:
        return False
    seconds = (end - start).total_seconds()
    distance = haversine_m(
        float(previous.latitude),
        float(previous.longitude),
        float(current.latitude),
        float(current.longitude),
    )
    if distance > MAX_SEGMENT_METERS:
        return False
    # Varias lecturas del mismo segundo son normales al arrancar el GPS; sin
    # un intervalo fiable solo se descarta un salto físicamente imposible.
    if seconds < 1:
        return distance <= 500
    return distance / seconds <= MAX_SPEED_MPS


def tracking_summary(
    *, delivery_id: str, reference: str, points: list[DeliveryTracking], delivered: bool = False
) -> DeliveryTrackingSummary:
    ordered = sorted(points, key=lambda point: point.recorded_at)
    distance = 0.0
    for previous, current in zip(ordered, ordered[1:]):
        if _segment_is_plausible(previous, current):
            distance += haversine_m(
                float(previous.latitude),
                float(previous.longitude),
                float(current.latitude),
                float(current.longitude),
            )
    last = ordered[-1] if ordered else None
    stale_seconds: int | None = None
    stale = True
    if last is not None:
        moment = ensure_utc(last.recorded_at) or utcnow()
        stale_seconds = max(0, int((utcnow() - moment).total_seconds()))
        stale = not delivered and stale_seconds > STALE_AFTER_SECONDS
    return DeliveryTrackingSummary(
        delivery_id=delivery_id,
        reference=reference,
        points=[point_to_read(point) for point in ordered],
        distance_m=round(distance, 2),
        last=point_to_read(last) if last else None,
        stale_seconds=stale_seconds,
        stale=stale,
    )


def signature_integrity(signature: DeliverySignature) -> str:
    try:
        path = resolve_stored_path(signature.signature_path)
    except Exception:
        return "file_missing"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return "ok" if digest == signature.signature_sha256 else "mismatch"


def signature_to_read(signature: DeliverySignature) -> dict:
    delivery = signature.delivery
    return {
        "delivery_id": signature.delivery_id,
        "reference": delivery.reference if delivery else "",
        "signer_name": signature.signer_name,
        "signer_document": signature.signer_document,
        "signed_at": signature.signed_at,
        "sha256": signature.signature_sha256,
        "size_bytes": signature.size_bytes,
        "mime_type": signature.mime_type,
        "image_url": f"/api/v1/deliveries/{signature.delivery_id}/signature/image",
        "integrity": signature_integrity(signature),
    }
