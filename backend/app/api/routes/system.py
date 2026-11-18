"""System metadata and health endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.config import get_settings
from app.core.db import get_db
from app.core.enums import PermissionCode
from app.core.timeutils import utcnow
from app.models import User
from app.schemas import (
    QueueEnqueued,
    QueueStatus,
    QueueTaskStatus,
    StorageStatus,
    SystemInfo,
)
from app.services import s3 as s3_storage
from app.worker import queue as task_queue

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
    "Tarjetas NFC con token opaco (solo hash SHA-256), emisión, revocación, grabación NDEF y lectura física",
    "Bolsa de horas: saldo real por contrato semanal, fichajes y ajustes justificados auditados",
    "Seguimiento GPS de repartos con puntos append-only, distancia Haversine y antigüedad de la señal",
    "Firma digital de entrega en PNG con SHA-256, verificación de integridad y bloqueo de re-firma",
    "Registro de llamadas con handoff tel:/sip:, adaptador webhook y callback firmado del proveedor",
    "Lector NFC en el navegador (Web NFC y lectores USB HID) y grabación de etiquetas NDEF",
    "Almacenamiento documental con backend local o S3 compatible (AWS, MinIO, Ceph), SHA-256 y caché de descarga",
    "Cola de tareas Celery sobre Redis con worker, beat, tarea de prueba y consulta de estado",
    "Voz neuronal Piper en el servidor (ONNX local), Edge TTS y OpenAI TTS, con caché por hash y fallback del navegador",
]

PENDING = [
    "Marcación automática con un proveedor SIP/API real: el adaptador webhook está probado, pero el sandbox no tiene operador ni credenciales",
    "Lectura GPS en segundo plano con la aplicación cerrada: el navegador solo comparte ubicación mientras Mi reparto está abierto y con permiso",
    "S3 de producción (AWS, MinIO o Ceph): el adaptador se prueba contra la API S3 emulada por moto; no hay clúster ni credenciales reales en el sandbox",
    "Redis gestionado con TLS y Sentinel/Cluster: la cola se prueba con Redis 7.2 compilado en local; la topología de producción debe validarse en su infraestructura",
    "Edge TTS y OpenAI TTS: el código está integrado, pero el sandbox no tiene salida a sus endpoints; la voz Piper local sí se ejecuta de punta a punta",
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
        phase="Fases 1-14 implementadas; S3, Redis/Celery y voz neuronal integrados. Los límites externos (S3/Redis gestionados, SIP y TTS en la nube) se declaran en Pendiente",
        implemented=IMPLEMENTED,
        pending=PENDING,
    )


@router.get("/storage", response_model=StorageStatus, summary="Estado del almacenamiento")
def storage_status(
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> StorageStatus:
    return StorageStatus(**s3_storage.status())


@router.get("/queue", response_model=QueueStatus, summary="Estado de la cola de trabajos")
def queue_status(
    _: User = Depends(require_permission(PermissionCode.INVENTORY_READ)),
) -> QueueStatus:
    return QueueStatus(**task_queue.status())


@router.post("/queue/ping", response_model=QueueEnqueued, summary="Encolar tarea de prueba")
def queue_ping(
    _: User = Depends(require_permission(PermissionCode.SETTINGS_MANAGE)),
) -> QueueEnqueued:
    task_id, state = task_queue.enqueue_ping()
    return QueueEnqueued(
        task_id=task_id,
        state=state,
        message="Tarea encolada; consulte su estado en /system/queue/{task_id}.",
    )


@router.get(
    "/queue/{task_id}",
    response_model=QueueTaskStatus,
    summary="Estado de una tarea de la cola",
)
def queue_task(
    task_id: str,
    _: User = Depends(require_permission(PermissionCode.SETTINGS_MANAGE)),
) -> QueueTaskStatus:
    return QueueTaskStatus(**task_queue.task_status(task_id))


@router.get("/health", summary="Estado del servicio")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "time_utc": utcnow().isoformat()}
