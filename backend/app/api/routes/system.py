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
    "Repartos con vehículos, palés precintados y expedición de stock al cargar",
    "Copias de seguridad con manifiesto SHA-256, restauración, humo y carga medidos",
    "Informes nativos en PDF paginado y Excel con resumen, filtros y totales",
    "Métricas Prometheus en /metrics: HTTP, latencias, base, almacenamiento y operación",
    "Informes programados por correo con historial de envío y ejecución desde cron",
    "Trazas OpenTelemetry de peticiones y SQL enmascaradas, con contexto W3C y X-Trace-ID",
    "Alertas gestionadas: reglas sobre indicadores reales, cooldown, reconocimiento y resolución",
    "OCR local de facturas en PDF o imagen, con propuesta de campos y revisión humana",
    "AURORA Voice: dictado y lectura en el navegador con consultas reales de stock, tareas y repartos",
    "Calibración del almacén con plano real y tiempos cronometrados, con ajuste por regresión",
    "Turnos de trabajo semanales con cobertura exigida, asignación y control de solapes",
    "Tarjetas NFC con token opaco (solo hash SHA-256), emisión, revocación y fichaje por lectura",
    "Bolsa de horas: saldo real por contrato semanal, fichajes y ajustes justificados auditados",
]

PENDING = [
    "Fase 8: integración telefónica SIP/API para llamadas reales",
    "Fase 8: seguimiento GPS de repartos en tiempo real",
    "Fase 8: firma digital de entrega en la ficha del reparto",
    "Integración física de lectores NFC: la API de fichaje por token ya es real, pero no se escriben ni leen etiquetas desde el navegador",
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
        phase="Fases 1-7 y 9-14 completas: operación, voz, OCR, alertas, turnos, NFC y bolsa de horas; queda la fase 8",
        implemented=IMPLEMENTED,
        pending=PENDING,
    )


@router.get("/health", summary="Estado del servicio")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "time_utc": utcnow().isoformat()}
