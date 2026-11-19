"""Prueba de humo contra una instancia de AURORA LOGISTICS AI en marcha.

Comprueba salud, autenticación y las lecturas principales de cada módulo, más
la entrega del frontend compilado. Pensada para ejecutarse tras cada despliegue:

    cd backend
    ../.venv/bin/python -m scripts.smoke_test --base-url https://aurora.example.com \
        --email admin@aurora.demo --password 'Aurora2026!'

Sale con código 1 si alguna comprobación falla.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field

import httpx

# (nombre, método, ruta, códigos aceptados)
CHECKS: list[tuple[str, str, str, tuple[int, ...]]] = [
    ("Salud", "GET", "/healthz", (200,)),
    ("Información del sistema", "GET", "/api/v1/system/info", (200,)),
    ("Estado del servicio", "GET", "/api/v1/system/health", (200,)),
    ("Almacenamiento documental", "GET", "/api/v1/system/storage", (200,)),
    ("Cola de tareas", "GET", "/api/v1/system/queue", (200,)),
    ("Informe de facturación", "GET", "/api/v1/reports/invoices.csv", (200,)),
    ("Informe de repartos", "GET", "/api/v1/reports/deliveries.csv", (200,)),
    ("Informe de plantilla", "GET", "/api/v1/reports/employees.csv", (200,)),
    ("Informe de incidencias", "GET", "/api/v1/reports/incidents.csv", (200,)),
    ("Informe de auditoría", "GET", "/api/v1/reports/audit.csv", (200,)),
    ("Panel de control", "GET", "/api/v1/dashboard", (200,)),
    ("Productos", "GET", "/api/v1/products?limit=5", (200,)),
    ("Ubicaciones", "GET", "/api/v1/locations?limit=5", (200,)),
    ("Palés", "GET", "/api/v1/pallets?limit=5", (200,)),
    ("Movimientos", "GET", "/api/v1/movements?limit=5", (200,)),
    ("Tareas", "GET", "/api/v1/tasks?limit=5", (200,)),
    ("Incidencias", "GET", "/api/v1/incidents?limit=5", (200,)),
    ("Reservas", "GET", "/api/v1/reservations?limit=5", (200,)),
    ("Facturas", "GET", "/api/v1/invoices?limit=5", (200,)),
    ("Repartos", "GET", "/api/v1/deliveries?limit=5", (200,)),
    ("Vehículos", "GET", "/api/v1/vehicles", (200,)),
    ("Optimización: slotting", "GET", "/api/v1/optimization/slotting?limit=3", (200,)),
    ("Mi jornada", "GET", "/api/v1/attendance/me", (200,)),
    ("Personas", "GET", "/api/v1/employees?limit=5", (200,)),
    ("Informe PDF de inventario", "GET", "/api/v1/reports/inventory.pdf", (200,)),
    ("Informe Excel de inventario", "GET", "/api/v1/reports/inventory.xlsx", (200,)),
    ("Informe PDF de movimientos", "GET", "/api/v1/reports/movements.pdf", (200,)),
    ("Informe Excel de movimientos", "GET", "/api/v1/reports/movements.xlsx", (200,)),
    ("Programaciones de informes", "GET", "/api/v1/report-schedules?limit=5", (200,)),
    ("Estado del correo saliente", "GET", "/api/v1/report-schedules/config", (200,)),
    ("Reglas de alerta", "GET", "/api/v1/alerts/rules?limit=5", (200,)),
    ("Indicadores de alerta", "GET", "/api/v1/alerts/metrics", (200,)),
    ("Configuración del OCR", "GET", "/api/v1/invoices/ocr/config", (200,)),
    ("Estado de AURORA Voice", "GET", "/api/v1/voice/status", (200,)),
    ("Calibración del almacén", "GET", "/api/v1/optimization/calibration", (200,)),
    ("Plan de turnos", "GET", "/api/v1/shifts/plan?date_from=2026-01-01&date_to=2026-01-02", (200,)),
    ("Tarjetas NFC", "GET", "/api/v1/nfc/cards?limit=5", (200,)),
    ("Bolsa de horas", "GET", "/api/v1/hours-bank", (200,)),
    ("Ajustes de bolsa de horas", "GET", "/api/v1/hours-bank/adjustments", (200,)),
    ("Mis repartos (conductor)", "GET", "/api/v1/deliveries/mine", (200,)),
    ("Configuración de llamadas", "GET", "/api/v1/calls/config", (200,)),
    ("Llamadas", "GET", "/api/v1/calls?limit=5", (200,)),
    ("Frontend: informes", "GET", "/informes/", (200,)),
    ("Frontend: alertas", "GET", "/alertas/", (200,)),
    ("Frontend: voz", "GET", "/voz/", (200,)),
    ("Frontend: turnos", "GET", "/turnos/", (200,)),
    ("Frontend: tarjetas NFC", "GET", "/tarjetas/", (200,)),
    ("Frontend: lector NFC", "GET", "/lector/", (200,)),
    ("Frontend: bolsa de horas", "GET", "/bolsa-horas/", (200,)),
    ("Frontend: mi reparto", "GET", "/mi-reparto/", (200,)),
    ("Frontend: llamadas", "GET", "/llamadas/", (200,)),
    ("Frontend: panel", "GET", "/", (200,)),
    ("Frontend: repartos", "GET", "/repartos/", (200,)),
    ("Frontend: sistema", "GET", "/sistema/", (200,)),
]


@dataclass
class Report:
    passed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


def run_checks(client: httpx.Client, checks: list[tuple[str, str, str, tuple[int, ...]]] | None = None) -> Report:
    checks = checks if checks is not None else CHECKS
    report = Report()
    for name, method, path, expected in checks:
        started = time.perf_counter()
        try:
            response = client.request(method, path)
            elapsed = (time.perf_counter() - started) * 1000
            if response.status_code in expected:
                report.passed += 1
                print(f"  OK   {name:<26} {response.status_code} {elapsed:6.0f} ms")
            else:
                report.failed += 1
                report.errors.append(f"{name}: HTTP {response.status_code} en {path}")
                print(f"  FALLO {name:<25} {response.status_code} en {path}")
        except httpx.HTTPError as exc:
            report.failed += 1
            report.errors.append(f"{name}: {exc}")
            print(f"  FALLO {name:<25} {exc}")
    return report


def login(client: httpx.Client, email: str, password: str) -> None:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    if "aurora_session" not in client.cookies:
        raise RuntimeError("El inicio de sesión no devolvió la cookie de sesión")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prueba de humo de AURORA")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="admin@aurora.demo")
    parser.add_argument("--password", default="Aurora2026!")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--skip-login", action="store_true", help="Solo comprobar rutas públicas")
    parser.add_argument("--metrics-token", default=None, help="Token Bearer para /metrics")
    args = parser.parse_args(argv)

    print(f"Prueba de humo contra {args.base_url}")
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=args.timeout) as client:
        health = client.get("/healthz")
        if health.status_code != 200:
            print(f"  FALLO Salud inicial: HTTP {health.status_code}")
            return 1
        if not args.skip_login:
            try:
                login(client, args.email, args.password)
                print(f"  OK   Sesión iniciada como {args.email}")
            except (httpx.HTTPError, RuntimeError) as exc:
                print(f"  FALLO Inicio de sesión: {exc}")
                return 1
        report = run_checks(client)

        headers = {"Authorization": f"Bearer {args.metrics_token}"} if args.metrics_token else {}
        metrics_response = client.get("/metrics", headers=headers)
        if metrics_response.status_code == 200 and "# TYPE aurora_http_requests_total" in metrics_response.text:
            report.passed += 1
            print(f"  OK   {'Métricas Prometheus':<26} {metrics_response.status_code}")
        else:
            report.failed += 1
            report.errors.append(f"Métricas Prometheus: HTTP {metrics_response.status_code}")
            print(f"  FALLO {'Métricas Prometheus':<25} {metrics_response.status_code}")

    print(f"\nResultado: {report.passed} correctas, {report.failed} fallidas")
    for error in report.errors:
        print(f"  - {error}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
