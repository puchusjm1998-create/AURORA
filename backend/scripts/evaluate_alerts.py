"""Evalúa las reglas de alerta operativas. Pensado para cron cada 5 minutos.

    cd backend
    ../.venv/bin/python -m scripts.evaluate_alerts --dry-run
    ../.venv/bin/python -m scripts.evaluate_alerts

Sale con 1 si alguna regla falló al evaluarse, para que el orquestador avise.
Crear alertas no es un error: es el resultado esperado de una condición real.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import AlertRule
from app.services.alerts import OPERATOR_SYMBOLS, evaluate_rules, metric_value


def parse_moment(value: str | None) -> datetime | None:
    if not value:
        return None
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluar alertas de AURORA")
    parser.add_argument("--dry-run", action="store_true", help="Mostrar valores sin crear alertas")
    parser.add_argument("--now", default=None, help="Fecha ISO para simular el momento (pruebas)")
    args = parser.parse_args(argv)
    moment = parse_moment(args.now)

    with SessionLocal() as db:
        if args.dry_run:
            rules = list(db.scalars(select(AlertRule).order_by(AlertRule.name)).all())
            print(f"{len(rules)} reglas configuradas")
            for rule in rules:
                value = metric_value(db, rule.metric, moment)
                print(
                    f"  [{'x' if rule.is_active else ' '}] {rule.name}: "
                    f"{value:.0f} {OPERATOR_SYMBOLS[rule.operator]} {rule.threshold:.0f} "
                    f"· {rule.metric.value}"
                )
            return 0
        result = evaluate_rules(db, now=moment)
        db.commit()

    for alert in result["alerts"]:
        extra = "" if alert.notified_at else " (sin correo)"
        print(f"ALERTA {alert.severity.value.upper():8} {alert.message}{extra}")
    print(
        f"Evaluadas: {result['evaluated']} · nuevas: {result['triggered']} "
        f"· omitidas por duplicado/cooldown: {result['skipped']} · errores: {result['errors']}"
    )
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
