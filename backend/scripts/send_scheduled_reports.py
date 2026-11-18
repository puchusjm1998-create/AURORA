"""Envía los informes programados vencidos. Pensado para cron o systemd timer.

    cd backend
    ../.venv/bin/python -m scripts.send_scheduled_reports --dry-run
    ../.venv/bin/python -m scripts.send_scheduled_reports

Sin SMTP configurado no modifica ninguna programación y sale con código 2.
Sale con 1 si algún envío falla, para que el orquestador pueda alertar.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from app.core.db import SessionLocal
from app.services.report_delivery import due_schedules, process_due, smtp_status


def parse_moment(value: str | None) -> datetime | None:
    if not value:
        return None
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enviar informes programados de AURORA")
    parser.add_argument("--dry-run", action="store_true", help="Solo listar los vencidos")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de envíos en esta ejecución")
    parser.add_argument("--now", default=None, help="Fecha ISO para simular el momento (pruebas)")
    args = parser.parse_args(argv)
    moment = parse_moment(args.now)

    status = smtp_status()
    with SessionLocal() as db:
        due = due_schedules(db, moment)
        if not status["configured"]:
            print(
                "SMTP no configurado (SMTP_HOST/SMTP_FROM). No se envía ni se avanza nada; "
                f"hay {len(due)} informes vencidos.",
                file=sys.stderr,
            )
            return 2
        if args.dry_run:
            print(f"SMTP: {status['host']}:{status['port']} · {len(due)} vencidos")
            for schedule in due:
                print(
                    f"  {schedule.name} · {schedule.report_kind.value}/{schedule.report_format.value} "
                    f"· vencido {schedule.next_run_at} · {', '.join(schedule.recipients)}"
                )
            return 0
        results = process_due(db, now=moment, limit=args.limit)

    for item in results:
        detail = "" if item["status"] == "sent" else f" · {item['detail']}"
        print(f"{item['status'].upper():6} {item['name']}{detail}")
    print(f"Total: {len(results)} informes procesados")
    return 1 if any(item["status"] == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
