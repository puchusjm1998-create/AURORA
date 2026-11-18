"""AURORA Voice: consultas operativas en lenguaje natural sobre datos reales.

El reconocimiento y la síntesis de voz ocurren en el navegador con la Web Speech
API (sin enviar audio a AURORA ni a terceros). El servidor interpreta el texto,
consulta la base de datos y devuelve una respuesta en español. El proveedor es
intercambiable mediante ``VOICE_PROVIDER``; el proveedor incluido es local y
determinista, no un LLM que pueda inventar datos.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.enums import (
    AlertMetric,
    DeliveryStatus,
    IncidentStatus,
    PermissionCode,
    TaskStatus,
)
from app.core.permissions import permissions_for_role
from app.models import Delivery, Incident, Location, Product, StockLevel, Task, User
from app.services.alerts import METRICS, metric_value

PROVIDER_NAME = "aurora-builtin"


@dataclass
class VoiceReply:
    intent: str
    confidence: float
    answer: str
    data: dict[str, Any] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _money(value: Decimal | float | int) -> str:
    return f"{Decimal(str(value)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _plain(value: Decimal | float | int) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _quantity(value: Decimal | float | int) -> str:
    numeric = Decimal(str(value))
    if numeric == numeric.to_integral_value():
        return f"{numeric:.0f}"
    return f"{numeric:.2f}".replace(".", ",")


STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "de", "del", "en", "por", "para", "que",
    "donde", "esta", "estan", "se", "encuentra", "hay", "cuanto", "cuanta", "cuantos",
    "cuantas", "stock", "existencias", "producto", "productos", "busca", "buscar",
    "dime", "por favor", "favor", "me", "puedes", "decir", "cual", "es",
}


def _extract_product_query(text: str) -> str:
    cleaned = _normalize(text)
    cleaned = re.sub(r"[¿?¡!.,;]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(
        r"^(donde (esta|estan|se encuentra|se encuentran)|localiza|localizame|"
        r"ubicacion (de|del)|busca|buscame|stock (de|del)|existencias (de|del)|"
        r"cuanto (hay|stock) (de|del)|cuantos? (hay|tenemos) (de|del)|"
        r"dime|me puedes decir)\s+",
        "",
        cleaned,
    )
    while re.match(r"^(el|la|los|las|un|una|producto|productos|del|de)\s+", cleaned):
        cleaned = re.sub(r"^(el|la|los|las|un|una|producto|productos|del|de)\s+", "", cleaned)
    cleaned = re.sub(r"\s+(en el almacen|en almacen|por favor)$", "", cleaned)
    return cleaned.strip()


def _search_products(db: Session, query: str, limit: int = 5) -> list[Product]:
    tokens = [token for token in query.split() if len(token) >= 2 and token not in STOPWORDS]
    if not tokens:
        return []
    filters = []
    for token in tokens[:6]:
        like = f"%{token}%"
        filters.append(
            or_(
                Product.name.ilike(like),
                Product.sku.ilike(like),
                Product.manufacturer_ref.ilike(like),
                Product.barcode.ilike(like),
            )
        )
    candidates = list(
        db.scalars(
            select(Product).where(Product.is_active.is_(True), or_(*filters)).limit(60)
        ).all()
    )
    if not candidates:
        # Fallback insensible a acentos: el LIKE de SQLite/PostgreSQL no lo es.
        candidates = list(
            db.scalars(select(Product).where(Product.is_active.is_(True)).limit(1000)).all()
        )

    def score(product: Product) -> int:
        haystack = _normalize(
            " ".join(
                filter(
                    None,
                    [
                        product.name,
                        product.sku,
                        product.manufacturer_ref,
                        product.barcode,
                    ],
                )
            )
        )
        return sum(1 for token in tokens if token in haystack)

    ranked = sorted(
        ((score(product), product) for product in candidates),
        key=lambda item: (-item[0], item[1].name),
    )
    matched = [product for points, product in ranked if points > 0]
    return matched[:limit]


def _stock_for(db: Session, product: Product) -> dict[str, Any]:
    rows = db.execute(
        select(
            Location.full_code,
            Location.label,
            func.coalesce(func.sum(StockLevel.quantity), 0),
            func.coalesce(func.sum(StockLevel.reserved_quantity), 0),
        )
        .join(StockLevel, StockLevel.location_id == Location.id)
        .where(StockLevel.product_id == product.id)
        .group_by(Location.full_code, Location.label)
        .order_by(Location.full_code)
    ).all()
    positions = [
        {
            "location_code": code,
            "label": label,
            "quantity": _plain(quantity),
            "reserved": _plain(reserved),
            "available": _plain(Decimal(str(quantity)) - Decimal(str(reserved))),
        }
        for code, label, quantity, reserved in rows
        if Decimal(str(quantity)) > 0
    ]
    on_hand = sum((Decimal(item["quantity"]) for item in positions), Decimal("0"))
    reserved_total = sum((Decimal(item["reserved"]) for item in positions), Decimal("0"))
    return {
        "on_hand": _plain(on_hand),
        "reserved": _plain(reserved_total),
        "available": _plain(on_hand - reserved_total),
        "positions": positions,
    }


def _product_reply(db: Session, text: str) -> VoiceReply:
    query = _extract_product_query(text)
    suggestions = [
        "¿Dónde está el producto tornillo M8?",
        "¿Cuánto stock hay de tuerca M8?",
        "¿Qué productos están bajo mínimo?",
    ]
    if not query:
        return VoiceReply(
            intent="product_help",
            confidence=0.4,
            answer="Dígame el nombre o la referencia del producto que quiere localizar.",
            suggestions=suggestions,
        )
    products = _search_products(db, query)
    if not products:
        return VoiceReply(
            intent="product_not_found",
            confidence=0.6,
            answer=f"No encuentro ningún producto activo que coincida con «{query}».",
            data={"query": query},
            suggestions=suggestions,
        )
    product = products[0]
    stock = _stock_for(db, product)
    positions = stock["positions"]
    if not positions:
        answer = (
            f"{product.name} ({product.sku}) no tiene stock físico en ninguna ubicación. "
            f"Mínimo configurado: {_quantity(product.min_stock)} {product.uom}."
        )
    else:
        first = positions[0]
        where = (
            f"está en {first['location_code']}"
            + (f" ({first['label']})" if first["label"] else "")
            if len(positions) == 1
            else f"está repartido en {len(positions)} ubicaciones; la primera es {first['location_code']}"
        )
        answer = (
            f"{product.name} ({product.sku}) {where}. "
            f"Hay {_quantity(stock['on_hand'])} {product.uom} físicas, "
            f"{_quantity(stock['available'])} disponibles y {_quantity(stock['reserved'])} reservadas."
        )
    return VoiceReply(
        intent="product_location",
        confidence=0.92,
        answer=answer,
        data={
            "query": query,
            "product": {
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
                "uom": product.uom,
                "min_stock": _plain(product.min_stock),
            },
            "stock": stock,
            "alternatives": [
                {"sku": item.sku, "name": item.name}
                for item in products[1:]
            ],
        },
        suggestions=suggestions,
    )


def _low_stock_reply(db: Session) -> VoiceReply:
    totals = (
        select(StockLevel.product_id, func.sum(StockLevel.quantity).label("qty"))
        .group_by(StockLevel.product_id)
        .subquery()
    )
    rows = db.execute(
        select(Product, func.coalesce(totals.c.qty, 0))
        .outerjoin(totals, totals.c.product_id == Product.id)
        .where(Product.is_active.is_(True), func.coalesce(totals.c.qty, 0) < Product.min_stock)
        .order_by((func.coalesce(totals.c.qty, 0) - Product.min_stock))
        .limit(8)
    ).all()
    if not rows:
        answer = "No hay productos activos por debajo de su stock mínimo."
    else:
        pieces = [
            f"{product.name} ({_quantity(quantity)} de {_quantity(product.min_stock)} {product.uom})"
            for product, quantity in rows[:5]
        ]
        answer = f"Hay {len(rows)} producto(s) bajo mínimo: " + "; ".join(pieces) + "."
    return VoiceReply(
        intent="low_stock",
        confidence=0.9,
        answer=answer,
        data={
            "count": len(rows),
            "products": [
                {
                    "sku": product.sku,
                    "name": product.name,
                    "quantity": str(quantity),
                    "min_stock": _plain(product.min_stock),
                    "uom": product.uom,
                }
                for product, quantity in rows
            ],
        },
        suggestions=["¿Dónde está el producto con menos stock?", "Resumen del almacén"],
    )


def _tasks_reply(db: Session) -> VoiceReply:
    open_states = (TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)
    count = int(db.scalar(select(func.count()).select_from(Task).where(Task.status.in_(open_states))) or 0)
    rows = db.scalars(
        select(Task)
        .where(Task.status.in_(open_states))
        .order_by(Task.priority, Task.due_at.is_(None), Task.due_at)
        .limit(5)
    ).all()
    if count == 0:
        answer = "No hay tareas abiertas en este momento."
    else:
        detail = "; ".join(f"{task.title} (prioridad {task.priority})" for task in rows)
        answer = f"Hay {count} tarea(s) abiertas. Las más urgentes: {detail}."
    return VoiceReply(
        intent="open_tasks",
        confidence=0.88,
        answer=answer,
        data={
            "count": count,
            "tasks": [
                {
                    "code": task.code,
                    "title": task.title,
                    "priority": task.priority,
                    "status": task.status.value,
                    "due_at": task.due_at.isoformat() if task.due_at else None,
                }
                for task in rows
            ],
        },
        suggestions=["¿Hay incidencias abiertas?", "¿Cuántos repartos quedan?"],
    )


def _incidents_reply(db: Session) -> VoiceReply:
    states = (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED)
    count = int(
        db.scalar(select(func.count()).select_from(Incident).where(Incident.status.in_(states))) or 0
    )
    rows = db.scalars(
        select(Incident).where(Incident.status.in_(states)).order_by(Incident.created_at.desc()).limit(5)
    ).all()
    if count == 0:
        answer = "No hay incidencias abiertas."
    else:
        detail = "; ".join(f"{item.title} ({item.severity.value})" for item in rows)
        answer = f"Hay {count} incidencia(s) abiertas o reconocidas: {detail}."
    return VoiceReply(
        intent="open_incidents",
        confidence=0.88,
        answer=answer,
        data={
            "count": count,
            "incidents": [
                {
                    "code": item.code,
                    "title": item.title,
                    "severity": item.severity.value,
                    "status": item.status.value,
                }
                for item in rows
            ],
        },
        suggestions=["¿Cuántas tareas quedan?", "Resumen del almacén"],
    )


def _deliveries_reply(db: Session) -> VoiceReply:
    states = (
        DeliveryStatus.DRAFT,
        DeliveryStatus.PREPARING,
        DeliveryStatus.READY,
        DeliveryStatus.LOADED,
        DeliveryStatus.IN_TRANSIT,
    )
    rows = db.scalars(
        select(Delivery)
        .where(Delivery.status.in_(states))
        .order_by(Delivery.planned_departure.is_(None), Delivery.planned_departure)
        .limit(5)
    ).all()
    if not rows:
        answer = "No hay repartos pendientes."
    else:
        detail = "; ".join(
            f"{item.reference} a {item.destination_name} ({item.status.value})" for item in rows
        )
        answer = f"Hay {len(rows)} reparto(s) pendientes: {detail}."
    return VoiceReply(
        intent="pending_deliveries",
        confidence=0.87,
        answer=answer,
        data={
            "count": len(rows),
            "deliveries": [
                {
                    "reference": item.reference,
                    "destination": item.destination_name,
                    "status": item.status.value,
                    "planned_departure": item.planned_departure.isoformat()
                    if item.planned_departure
                    else None,
                }
                for item in rows
            ],
        },
        suggestions=["¿Dónde está el palé PRG-2026-001?", "Resumen del almacén"],
    )


def _summary_reply(db: Session, permissions: set[str]) -> VoiceReply:
    open_tasks = metric_value(db, AlertMetric.OPEN_TASKS)
    open_incidents = metric_value(db, AlertMetric.OPEN_INCIDENTS)
    pending = metric_value(db, AlertMetric.PENDING_DELIVERIES)
    low_stock = metric_value(db, AlertMetric.LOW_STOCK_PRODUCTS)
    units = metric_value(db, AlertMetric.STOCK_UNITS)
    parts = [f"hay {_quantity(units)} unidades en stock", f"{_quantity(low_stock)} productos bajo mínimo"]
    if PermissionCode.TASKS_WRITE.value in permissions:
        parts.append(f"{_quantity(open_tasks)} tareas abiertas")
    if PermissionCode.INCIDENTS_READ in permissions:
        parts.append(f"{_quantity(open_incidents)} incidencias abiertas")
    if PermissionCode.DELIVERIES_READ in permissions:
        parts.append(f"{_quantity(pending)} repartos pendientes")
    return VoiceReply(
        intent="summary",
        confidence=0.9,
        answer="Resumen del almacén: " + ", ".join(parts) + ".",
        data={
            "stock_units": _plain(units),
            "low_stock_products": _plain(low_stock),
            "open_tasks": _plain(open_tasks),
            "open_incidents": _plain(open_incidents),
            "pending_deliveries": _plain(pending),
        },
        suggestions=["¿Qué productos están bajo mínimo?", "¿Dónde está el producto tornillo M8?"],
    )


def _permissions(db: Session, user: User) -> set[str]:
    return {code.value if hasattr(code, "value") else str(code) for code in permissions_for_role(db, user.role_id)}


def interpret(db: Session, text: str, user: User) -> VoiceReply:
    normalized = _normalize(text)
    if not normalized:
        return VoiceReply(
            intent="empty",
            confidence=0.0,
            answer="No he recibido ninguna frase. Pulse el micrófono e inténtelo de nuevo.",
        )
    permissions = _permissions(db, user)

    if re.search(r"resumen|como esta|estado general|panorama|situacion", normalized):
        return _summary_reply(db, permissions)
    if re.search(r"bajo minimo|reponer|reposicion|falta stock|sin stock|agotad", normalized):
        return _low_stock_reply(db)
    if re.search(r"tarea|tareas|pendiente[s]? de hacer|trabajo", normalized):
        if PermissionCode.TASKS_WRITE.value not in permissions:
            return VoiceReply(
                intent="forbidden",
                confidence=0.7,
                answer="Su perfil puede consultar sus tareas en /tareas, pero no el resumen global del almacén.",
                suggestions=["¿Dónde está el producto tornillo M8?", "Resumen del almacén"],
            )
        return _tasks_reply(db)
    if re.search(r"incidencia|averia|problema|rotura", normalized):
        if PermissionCode.INCIDENTS_READ.value not in permissions:
            return VoiceReply(
                intent="forbidden",
                confidence=0.7,
                answer="Su perfil no tiene permiso para consultar incidencias.",
            )
        return _incidents_reply(db)
    if re.search(r"reparto|camion|entrega|envio|ruta", normalized):
        if PermissionCode.DELIVERIES_READ.value not in permissions:
            return VoiceReply(
                intent="forbidden",
                confidence=0.7,
                answer="Su perfil no tiene permiso para consultar repartos.",
            )
        return _deliveries_reply(db)
    if re.search(r"donde|ubicacion|localiza|estanteria|palet|stock|existencia|cuanto hay|unidades", normalized):
        return _product_reply(db, text)

    products = _search_products(db, normalized)
    if products:
        reply = _product_reply(db, text)
        reply.confidence = min(reply.confidence, 0.6)
        return reply
    return VoiceReply(
        intent="unknown",
        confidence=0.2,
        answer=(
            "Puedo consultar ubicaciones y stock de productos, productos bajo mínimo, "
            "tareas, incidencias, repartos y el resumen del almacén. ¿Qué necesita?"
        ),
        suggestions=[
            "¿Dónde está el producto tornillo M8?",
            "¿Qué productos están bajo mínimo?",
            "¿Hay incidencias abiertas?",
            "Resumen del almacén",
        ],
    )


PROVIDERS: dict[str, Callable[[Session, str, User], VoiceReply]] = {
    PROVIDER_NAME: interpret,
}


def provider_status() -> dict[str, Any]:
    return {
        "provider": PROVIDER_NAME,
        "provider_label": "Consultas AURORA locales (deterministas, sin LLM externo)",
        "available": True,
        "interchangeable": True,
        "stt": "Web Speech API del navegador",
        "tts": "SpeechSynthesis del navegador",
        "audio_leaves_device": False,
        "llm_configured": False,
        "locale": "es-ES",
        "capabilities": [
            "ubicación y stock de un producto",
            "productos bajo mínimo",
            "tareas abiertas",
            "incidencias abiertas",
            "repartos pendientes",
            "resumen del almacén",
        ],
    }


def answer(db: Session, text: str, user: User, *, provider: str = PROVIDER_NAME) -> VoiceReply:
    implementation = PROVIDERS.get(provider, interpret)
    return implementation(db, text, user)
