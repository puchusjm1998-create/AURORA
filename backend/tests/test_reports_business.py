"""Informes de facturación, repartos y plantilla: datos reales y permisos."""

from __future__ import annotations

import json
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import app
from tests.conftest import create_structure, login


def _invoice(admin_client, structure) -> None:
    response = admin_client.post(
        "/api/v1/invoices",
        data={
            "number": "FRA-2026-777",
            "invoice_date": "2026-11-10",
            "due_date": "2026-12-10",
            "supplier_id": structure["supplier_id"],
            "lines_json": json.dumps(
                [
                    {
                        "description": "Palé de prueba",
                        "quantity": "2",
                        "unit_price": "50",
                        "tax_rate": "21",
                    }
                ]
            ),
        },
    )
    assert response.status_code == 201, response.text


def _delivery(admin_client) -> None:
    response = admin_client.post(
        "/api/v1/deliveries",
        json={
            "destination_name": "Cliente Informe S.A.",
            "destination_address": "Calle del Informe 7, Cartagena",
            "planned_departure": "2030-05-01T08:00:00Z",
        },
    )
    assert response.status_code == 201, response.text


def _employee(admin_client) -> None:
    response = admin_client.post(
        "/api/v1/employees",
        json={
            "first_name": "Ana",
            "last_name": "Informe",
            "department": "Logística",
            "position": "Encargada",
            "weekly_hours": "37.5",
            "status": "active",
            "hire_date": "2025-01-15",
        },
    )
    assert response.status_code == 201, response.text


def test_invoice_report_csv_pdf_xlsx(admin_client):
    structure = create_structure(admin_client)
    _invoice(admin_client, structure)

    csv = admin_client.get("/api/v1/reports/invoices.csv")
    assert csv.status_code == 200, csv.text
    assert csv.text.startswith("\ufeff")
    lines = csv.text.strip().splitlines()
    assert "Número;Proveedor;Fecha" in lines[0]
    assert len(lines) == 2  # cabecera + factura (los totales van en PDF/Excel)
    assert "FRA-2026-777" in lines[1]
    assert "Proveedor Test S.L." in lines[1]
    assert "100.00" in lines[1]  # 2 × 50 sin IVA
    assert "Recibida" in lines[1]

    pdf = admin_client.get("/api/v1/reports/invoices.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-") and pdf.content.rstrip().endswith(b"%%EOF")

    xlsx = admin_client.get("/api/v1/reports/invoices.xlsx")
    assert xlsx.status_code == 200
    workbook = load_workbook(BytesIO(xlsx.content))
    assert workbook.sheetnames == ["Resumen", "Facturas"]
    sheet = workbook["Facturas"]
    assert sheet["A1"].value == "Número"
    assert sheet["A2"].value == "FRA-2026-777"
    assert sheet["B2"].value == "Proveedor Test S.L."
    assert float(sheet["J2"].value) == 121.0  # total con IVA


def test_delivery_report_csv_and_filters(admin_client):
    _delivery(admin_client)

    csv = admin_client.get("/api/v1/reports/deliveries.csv")
    assert csv.status_code == 200, csv.text
    lines = csv.text.strip().splitlines()
    assert "Referencia;Estado;Destino" in lines[0]
    assert len(lines) == 2
    assert "Cliente Informe S.A." in lines[1]
    assert "Borrador" in lines[1]

    future = admin_client.get(
        "/api/v1/reports/deliveries.csv",
        params={"date_from": "2099-01-01T00:00:00Z"},
    )
    assert future.status_code == 200
    assert len(future.text.strip().splitlines()) == 1  # solo cabecera

    pdf = admin_client.get("/api/v1/reports/deliveries.pdf", params={"status": "draft"})
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")


def test_employee_report_xlsx_and_active_filter(admin_client):
    _employee(admin_client)

    csv = admin_client.get("/api/v1/reports/employees.csv")
    assert csv.status_code == 200, csv.text
    lines = csv.text.strip().splitlines()
    assert "Código;Nombre;Departamento" in lines[0]
    assert "Ana Informe" in lines[1]
    assert "37.50" in lines[1]

    xlsx = admin_client.get("/api/v1/reports/employees.xlsx")
    assert xlsx.status_code == 200
    workbook = load_workbook(BytesIO(xlsx.content))
    sheet = workbook["Plantilla"]
    assert sheet["B2"].value == "Ana Informe"
    assert float(sheet["E2"].value) == 37.5
    assert sheet["F2"].value == "Activo"
    assert sheet.cell(row=3, column=5).value == 37.5  # fila de totales

    inactive = admin_client.get(
        "/api/v1/reports/employees.csv", params={"active_only": True}
    )
    assert inactive.status_code == 200
    assert "Ana Informe" in inactive.text


def test_incident_report_csv_pdf_xlsx_and_filters(admin_client):
    structure = create_structure(admin_client)
    created = admin_client.post(
        "/api/v1/incidents",
        json={
            "title": "Palé dañado en el informe",
            "description": "Esquina rota",
            "incident_type": "damage",
            "severity": "high",
            "location_id": structure["location_id"],
            "product_id": structure["product_id"],
        },
    )
    assert created.status_code == 201, created.text
    code = created.json()["code"]

    csv = admin_client.get("/api/v1/reports/incidents.csv")
    assert csv.status_code == 200, csv.text
    assert "Código;Título;Tipo;Severidad" in csv.text
    assert code in csv.text
    assert "Daño" in csv.text and "Alta" in csv.text and "Abierta" in csv.text
    assert "Proveedor Test" not in csv.text  # sin columnas ajenas

    filtered = admin_client.get(
        "/api/v1/reports/incidents.csv", params={"severity": "low"}
    )
    assert filtered.status_code == 200
    assert code not in filtered.text

    pdf = admin_client.get("/api/v1/reports/incidents.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")

    xlsx = admin_client.get("/api/v1/reports/incidents.xlsx")
    assert xlsx.status_code == 200
    workbook = load_workbook(BytesIO(xlsx.content))
    sheet = workbook["Incidencias"]
    assert sheet["A2"].value == code
    assert sheet["D2"].value == "Alta"


def test_audit_report_contains_actions_and_filters(admin_client):
    create_structure(admin_client)
    csv = admin_client.get("/api/v1/reports/audit.csv")
    assert csv.status_code == 200, csv.text
    assert "Fecha (UTC);Actor;Acción" in csv.text
    assert "warehouse.created" in csv.text
    assert "product.created" in csv.text

    filtered = admin_client.get(
        "/api/v1/reports/audit.csv", params={"action": "warehouse.created"}
    )
    assert filtered.status_code == 200
    assert "warehouse.created" in filtered.text
    assert "product.created" not in filtered.text

    pdf = admin_client.get("/api/v1/reports/audit.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    xlsx = admin_client.get("/api/v1/reports/audit.xlsx")
    assert xlsx.status_code == 200
    workbook = load_workbook(BytesIO(xlsx.content))
    assert workbook.sheetnames == ["Resumen", "Auditoría"]
    assert workbook["Auditoría"]["C1"].value == "Acción"


def test_audit_export_requires_audit_read(client, users):
    manager = login(TestClient(app), "manager@test.local")
    assert manager.get("/api/v1/reports/audit.csv").status_code == 403
    assert manager.get("/api/v1/reports/audit.pdf").status_code == 403
    assert manager.get("/api/v1/reports/audit.xlsx").status_code == 403
    auditor = login(TestClient(app), "auditor@test.local")
    assert auditor.get("/api/v1/reports/audit.csv").status_code == 200


def test_business_reports_require_export_permission(worker_client):
    for path in (
        "/api/v1/reports/invoices.csv",
        "/api/v1/reports/invoices.pdf",
        "/api/v1/reports/invoices.xlsx",
        "/api/v1/reports/deliveries.csv",
        "/api/v1/reports/deliveries.pdf",
        "/api/v1/reports/deliveries.xlsx",
        "/api/v1/reports/employees.csv",
        "/api/v1/reports/employees.pdf",
        "/api/v1/reports/employees.xlsx",
        "/api/v1/reports/incidents.csv",
        "/api/v1/reports/incidents.pdf",
        "/api/v1/reports/incidents.xlsx",
        "/api/v1/reports/audit.csv",
        "/api/v1/reports/audit.pdf",
        "/api/v1/reports/audit.xlsx",
    ):
        assert worker_client.get(path).status_code == 403, path
