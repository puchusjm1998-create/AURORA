"""System metadata and health endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.timeutils import utcnow
from app.schemas import SystemInfo

router = APIRouter(prefix="/system", tags=["Sistema"])
settings = get_settings()

IMPLEMENTED = [
    "Autenticación con sesiones revocables y contraseñas bcrypt",
    "Permisos jerárquicos (5 niveles) comprobados en el servidor",
    "Inventario con existencias físicas, reservadas, disponibles y en tránsito",
    "Almacenes y ubicaciones jerárquicas con código imprimible QR",
    "Palés, objetos unitarios y trazabilidad completa",
    "Entradas, salidas, movimientos internos y ajustes auditados",
    "Historial de movimientos inmutable y auditoría append-only",
    "Facturas: carga de original, líneas y conciliación con recepciones",
    "Informes CSV de inventario y movimientos",
    "Escaneo QR desde cámara del móvil y etiquetas imprimibles",
    "Reservas de stock por pedido, posición y caducidad",
    "Tareas de almacén con asignación, prioridad y cierre auditado",
    "Incidencias de almacén con severidad, responsable y resolución auditada",
    "Fichaje de jornada con pausas, estados y resumen de horas auditado",
    "Sugerencias de ubicación y rutas de picking con modelo geométrico declarado",
]

PENDING = [
    "Fase 4: OCR automático de facturas (requiere proveedor externo configurado)",
    "Fase 5: AURORA Voice (reconocimiento y síntesis de voz, IA intercambiable)",
    "Fase 6: calibración fina con plano real, tiempos medidos y turnos de trabajo",
    "Fase 7: tarjetas digitales NFC, planificación de turnos y bolsa de horas",
    "Fase 8: repartos, integración telefónica SIP/API y gestión avanzada de incidencias",
    "Fase 9: pruebas de carga, copias de seguridad automatizadas y despliegue definitivo",
]


@router.get("/info", response_model=SystemInfo, summary="Información del sistema")
def system_info() -> SystemInfo:
    return SystemInfo(
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        demo_mode=settings.demo_mode,
        server_time_utc=utcnow().isoformat().replace("+00:00", "Z"),
        warehouse_timezone=settings.warehouse_timezone,
        phase="Fases 1-3 + fichaje y optimización: inventario, tareas, incidencias, jornada y rutas",
        implemented=IMPLEMENTED,
        pending=PENDING,
    )


@router.get("/health", summary="Estado del servicio")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "time_utc": utcnow().isoformat()}
