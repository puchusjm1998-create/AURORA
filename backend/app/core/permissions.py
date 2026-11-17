"""Role based access control.

Permissions are stored in the database (``roles``/``permissions``/
``role_permissions``) and checked on the server for every protected endpoint.
The matrix below is the source of truth for seeding and for administration.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PermissionCode as P
from app.core.enums import ROLE_DEFINITIONS
from app.models import Permission, Role, RolePermission

ROLE_CODES: dict[int, str] = {
    1: "admin",
    2: "logistics_manager",
    3: "supervisor",
    4: "worker",
    5: "auditor",
}

READ_ONLY = {
    P.INVENTORY_READ,
    P.LOCATIONS_READ,
    P.PALLETS_READ,
    P.MOVEMENTS_READ,
    P.RESERVATIONS_READ,
    P.INVOICES_READ,
    P.WORKERS_READ,
    P.REPORTS_READ,
    P.REPORTS_EXPORT,
    P.INCIDENTS_READ,
    P.DELIVERIES_READ,
    P.ATTENDANCE_READ,
}

ROLE_PERMISSIONS: dict[int, set[P]] = {
    1: set(P),  # principal administrator: everything
    2: {
        P.INVENTORY_READ, P.INVENTORY_WRITE,
        P.LOCATIONS_READ, P.LOCATIONS_WRITE,
        P.PALLETS_READ, P.PALLETS_WRITE,
        P.MOVEMENTS_READ, P.MOVEMENTS_WRITE, P.MOVEMENTS_CONFIRM, P.MOVEMENTS_CANCEL,
        P.RESERVATIONS_READ, P.RESERVATIONS_WRITE,
        P.INVOICES_READ, P.INVOICES_WRITE, P.INVOICES_RECONCILE,
        P.WORKERS_READ, P.ATTENDANCE_READ, P.ATTENDANCE_MANAGE,
        P.DELIVERIES_READ, P.DELIVERIES_WRITE, P.INCIDENTS_READ, P.INCIDENTS_WRITE,
        P.REPORTS_READ, P.REPORTS_EXPORT, P.AI_USE, P.AI_APPROVE_ACTIONS,
    },
    3: {
        P.INVENTORY_READ, P.INVENTORY_WRITE,
        P.LOCATIONS_READ, P.LOCATIONS_WRITE,
        P.PALLETS_READ, P.PALLETS_WRITE,
        P.MOVEMENTS_READ, P.MOVEMENTS_WRITE, P.MOVEMENTS_CONFIRM,
        P.RESERVATIONS_READ, P.RESERVATIONS_WRITE,
        P.INVOICES_READ, P.INVOICES_WRITE,
        P.WORKERS_READ, P.ATTENDANCE_READ, P.INCIDENTS_READ, P.INCIDENTS_WRITE,
        P.DELIVERIES_READ, P.REPORTS_READ, P.REPORTS_EXPORT, P.AI_USE,
    },
    4: {
        P.INVENTORY_READ, P.LOCATIONS_READ, P.PALLETS_READ,
        P.MOVEMENTS_READ, P.MOVEMENTS_WRITE, P.MOVEMENTS_CONFIRM,
        P.AI_USE,
    },
    5: READ_ONLY | {P.AUDIT_READ},
}

PERMISSION_DESCRIPTIONS: dict[str, str] = {
    "inventory.read": "Consultar productos y existencias",
    "inventory.write": "Crear y modificar productos",
    "inventory.delete": "Desactivar productos y datos maestros",
    "locations.read": "Consultar almacenes y ubicaciones",
    "locations.write": "Crear y modificar ubicaciones",
    "pallets.read": "Consultar palés y su contenido",
    "pallets.write": "Crear, llenar y mover palés",
    "movements.read": "Consultar el historial de movimientos",
    "movements.write": "Registrar movimientos de stock",
    "movements.confirm": "Confirmar movimientos y aplicar stock",
    "movements.cancel": "Cancelar movimientos en borrador",
    "reservations.read": "Consultar reservas de stock",
    "reservations.write": "Crear y liberar reservas",
    "invoices.read": "Consultar facturas",
    "invoices.write": "Subir facturas y registrar líneas",
    "invoices.reconcile": "Conciliar facturas con recepciones",
    "workers.read": "Consultar personal",
    "workers.write": "Gestionar personal",
    "attendance.read": "Consultar registros horarios",
    "attendance.manage": "Gestionar y corregir registros horarios",
    "deliveries.read": "Consultar repartos",
    "deliveries.write": "Gestionar repartos",
    "incidents.read": "Consultar incidencias",
    "incidents.write": "Registrar y gestionar incidencias",
    "reports.read": "Consultar informes",
    "reports.export": "Exportar informes",
    "audit.read": "Consultar la auditoría del sistema",
    "users.manage": "Gestionar usuarios y cuentas",
    "roles.manage": "Gestionar roles y permisos",
    "settings.manage": "Modificar configuración del sistema",
    "ai.use": "Utilizar AURORA Voice",
    "ai.approve_actions": "Aprobar acciones propuestas por la IA",
    "calls.manage": "Gestionar llamadas e integración telefónica",
}

_permission_cache: dict[int, frozenset[str]] = {}


def invalidate_permission_cache() -> None:
    _permission_cache.clear()


def seed_rbac(db: Session) -> None:
    """Idempotently create roles, permissions and their grants."""
    existing_permissions = {p.code for p in db.scalars(select(Permission)).all()}
    for code in P:
        for_cat = code.value.split(".")[0]
        if code.value not in existing_permissions:
            db.add(Permission(code=code.value, description=PERMISSION_DESCRIPTIONS.get(code.value, ""), category=for_cat))

    existing_roles = {r.level: r for r in db.scalars(select(Role)).all()}
    for level, (name, description) in ROLE_DEFINITIONS.items():
        role = existing_roles.get(level)
        if role is None:
            role = Role(code=ROLE_CODES[level], name=name, description=description, level=level)
            db.add(role)
            db.flush()
        else:
            role.name = name
            role.description = description
            role.code = ROLE_CODES[level]

    db.flush()

    roles_by_level = {r.level: r for r in db.scalars(select(Role)).all()}
    current: dict[int, set[str]] = {}
    for rp in db.scalars(select(RolePermission)).all():
        current.setdefault(rp.role_id, set()).add(rp.permission_code)

    for level, permissions in ROLE_PERMISSIONS.items():
        role = roles_by_level[level]
        wanted = {p.value for p in permissions}
        have = current.get(role.id, set())
        for code in wanted - have:
            db.add(RolePermission(role_id=role.id, permission_code=code))
        for code in have - wanted:
            db.query(RolePermission).filter_by(role_id=role.id, permission_code=code).delete()
    db.flush()
    invalidate_permission_cache()


def permissions_for_role(db: Session, role_id: int) -> frozenset[str]:
    cached = _permission_cache.get(role_id)
    if cached is not None:
        return cached
    rows = db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id == role_id)).all()
    result = frozenset(rows)
    _permission_cache[role_id] = result
    return result
