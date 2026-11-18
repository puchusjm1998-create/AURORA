"""Informes nativos PDF y Excel: contenido real, formatos y permisos."""

from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook

from app.services.reports import ReportTable, format_number, select_columns
from tests.conftest import create_structure


def _reception(admin_client, structure, quantity="10") -> None:
    response = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "reception",
            "product_id": structure["product_id"],
            "quantity": quantity,
            "to_location_id": structure["location_id"],
            "reason": "Recepción para informe",
            "physical_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text


def test_inventory_pdf_is_a_real_document(admin_client):
    structure = create_structure(admin_client)
    _reception(admin_client, structure)

    response = admin_client.get("/api/v1/reports/inventory.pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert ".pdf" in response.headers["content-disposition"]
    content = response.content
    assert content.startswith(b"%PDF-")
    assert content.rstrip().endswith(b"%%EOF")
    assert content.count(b"/Type /Page") >= 1
    assert len(content) > 1500

    filtered = admin_client.get(
        "/api/v1/reports/inventory.pdf", params={"warehouse_id": structure["warehouse_id"]}
    )
    assert filtered.status_code == 200
    assert filtered.content.startswith(b"%PDF-")

    movements = admin_client.get("/api/v1/reports/movements.pdf")
    assert movements.status_code == 200
    assert movements.headers["content-type"] == "application/pdf"
    assert movements.content.startswith(b"%PDF-")
    assert b"%%EOF" in movements.content[-10:]


def test_inventory_xlsx_has_summary_data_and_totals(admin_client):
    structure = create_structure(admin_client)
    _reception(admin_client, structure, "10")

    response = admin_client.get("/api/v1/reports/inventory.xlsx")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert ".xlsx" in response.headers["content-disposition"]
    assert response.content.startswith(b"PK")

    workbook = load_workbook(BytesIO(response.content))
    assert workbook.sheetnames == ["Resumen", "Inventario"]
    summary = workbook["Resumen"]
    assert summary["A1"].value == "Informe de inventario"
    assert summary["A5"].value == "Filas exportadas"
    assert summary["B5"].value == 1
    assert workbook.properties.creator == "AURORA LOGISTICS AI"

    sheet = workbook["Inventario"]
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:N2"
    assert [cell.value for cell in sheet[1]][:4] == ["SKU", "Producto", "Categoría", "Ud."]
    assert sheet["A2"].value == structure["sku"]
    assert sheet["F2"].value == structure["location_code"]
    assert float(sheet["H2"].value) == 10.0
    assert sheet["H2"].number_format == "#,##0.000"
    assert float(sheet["J2"].value) == 10.0  # disponible
    assert float(sheet["M2"].value) == 100.0  # valor a coste
    assert sheet["M2"].number_format == "#,##0.00"
    assert sheet["P2"].value is None

    total = 3
    assert sheet.cell(row=total, column=1).value == "Total"
    assert float(sheet.cell(row=total, column=8).value) == 10.0
    assert float(sheet.cell(row=total, column=13).value) == 100.0
    assert sheet.cell(row=total, column=1).font.bold is True


def test_movements_xlsx_keeps_dates_and_quantities(admin_client):
    structure = create_structure(admin_client)
    _reception(admin_client, structure, "7.5")

    response = admin_client.get("/api/v1/reports/movements.xlsx")
    assert response.status_code == 200, response.text
    workbook = load_workbook(BytesIO(response.content))
    sheet = workbook["Movimientos"]
    headers = [cell.value for cell in sheet[1]]
    assert headers[:3] == ["Referencia", "Fecha (UTC)", "Tipo"]
    assert headers[-1] == "Confirmación física"
    assert sheet["A2"].value.startswith("AUR-")
    assert float(sheet["G2"].value) == 7.5
    assert sheet["G2"].number_format == "#,##0.000"
    assert sheet["M2"].value == "Sí"


def test_native_reports_require_export_permission(worker_client):
    for path in (
        "/api/v1/reports/inventory.pdf",
        "/api/v1/reports/inventory.xlsx",
        "/api/v1/reports/movements.pdf",
        "/api/v1/reports/movements.xlsx",
    ):
        assert worker_client.get(path).status_code == 403, path


def test_report_helpers_keep_spanish_number_format_and_columns():
    assert format_number("1234.5", "qty") == "1.234,500"
    assert format_number("1234.5", "money") == "1.234,50"
    table = ReportTable(
        title="Prueba",
        subtitle="Sub",
        headers=["A", "B", "C"],
        rows=[["x", "1.5", "9"]],
        formats={1: "qty"},
        totals=["Total", "1.5", ""],
        meta=[("Periodo", "Hoy")],
        sheet_name="Prueba",
    )
    view = select_columns(table, [0, 2])
    assert view.headers == ["A", "C"]
    assert view.rows == [["x", "9"]]
    assert view.formats == {}
    assert view.totals == ["Total", ""]
