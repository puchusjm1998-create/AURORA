"""Pallet lifecycle, QR labels, scanning and invoice reconciliation."""

from __future__ import annotations

from datetime import date

from tests.conftest import create_structure


def _second_location(admin_client, structure, aisle="P06"):
    response = admin_client.post(
        "/api/v1/locations",
        json={
            "warehouse_id": structure["warehouse_id"],
            "aisle": aisle,
            "rack": "EA",
            "level": "N01",
            "position": "POS01",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_pallet_lifecycle(admin_client):
    structure = create_structure(admin_client)
    pallet = admin_client.post(
        "/api/v1/pallets",
        json={"warehouse_id": structure["warehouse_id"], "location_id": structure["location_id"]},
    )
    assert pallet.status_code == 201, pallet.text
    pallet = pallet.json()
    assert pallet["code"].startswith("AUR-PAL-")

    add = admin_client.post(
        f"/api/v1/pallets/{pallet['id']}/items",
        json={"product_id": structure["product_id"], "quantity": "50"},
    )
    assert add.status_code == 200, add.text
    assert float(add.json()["total_units"]) == 50
    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["on_hand"]) == 50

    sealed = admin_client.post(f"/api/v1/pallets/{pallet['id']}/seal")
    assert sealed.status_code == 200
    assert sealed.json()["status"] == "sealed"

    duplicate_add = admin_client.post(
        f"/api/v1/pallets/{pallet['id']}/items",
        json={"product_id": structure["product_id"], "quantity": "5"},
    )
    assert duplicate_add.status_code == 409

    second = _second_location(admin_client, structure)
    moved = admin_client.post(
        f"/api/v1/pallets/{pallet['id']}/move",
        json={"destination_location_id": second["id"]},
    )
    assert moved.status_code == 200, moved.text
    pallet_data = admin_client.get(f"/api/v1/pallets/{pallet['id']}").json()
    assert pallet_data["location_code"] == second["full_code"]

    whereabouts = admin_client.get(
        f"/api/v1/products/{structure['product_id']}/whereabouts"
    ).json()
    assert whereabouts["positions"][0]["location_code"] == second["full_code"]

    shipped = admin_client.post(
        f"/api/v1/pallets/{pallet['id']}/ship", json={"document_ref": "ALB-001"}
    )
    assert shipped.status_code == 200, shipped.text
    pallet_data = admin_client.get(f"/api/v1/pallets/{pallet['id']}").json()
    assert pallet_data["status"] == "shipped"

    product = admin_client.get(f"/api/v1/products/{structure['product_id']}").json()
    assert float(product["stock"]["on_hand"]) == 0

    cannot_reship = admin_client.post(f"/api/v1/pallets/{pallet['id']}/ship", json={})
    assert cannot_reship.status_code == 409


def test_pallet_capacity_is_respected(admin_client):
    structure = create_structure(admin_client)
    first = admin_client.post(
        "/api/v1/pallets",
        json={"warehouse_id": structure["warehouse_id"], "location_id": structure["location_id"]},
    ).json()
    # capacity_pallets is 2 for the created location.
    second = admin_client.post(
        "/api/v1/pallets",
        json={"warehouse_id": structure["warehouse_id"], "location_id": structure["location_id"]},
    ).json()
    third = admin_client.post(
        "/api/v1/pallets",
        json={"warehouse_id": structure["warehouse_id"]},
    ).json()
    assert first["code"] != second["code"]

    response = admin_client.post(
        f"/api/v1/pallets/{third['id']}/move",
        json={"destination_location_id": structure["location_id"]},
    )
    # Location already hosts two pallets (capacity 2) -> conflict.
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"

    full_location = admin_client.post(
        "/api/v1/pallets",
        json={"warehouse_id": structure["warehouse_id"], "location_id": structure["location_id"]},
    )
    assert full_location.status_code == 409


def test_qr_label_and_scan_resolution(admin_client):
    structure = create_structure(admin_client)
    label = admin_client.get(f"/api/v1/qr/labels/product/{structure['product_id']}")
    assert label.status_code == 200
    payload = label.json()["payload"]
    assert payload == f"aurora://product/{structure['sku']}"

    image = admin_client.get("/api/v1/qr", params={"payload": payload})
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"

    scan = admin_client.get("/api/v1/scan/resolve", params={"code": payload})
    assert scan.status_code == 200
    assert scan.json()["target_type"] == "product"

    location_scan = admin_client.get(
        "/api/v1/scan/resolve", params={"code": structure["location_code"]}
    )
    assert location_scan.status_code == 200
    assert location_scan.json()["target_type"] == "location"

    invalid = admin_client.get("/api/v1/qr", params={"payload": "https://evil.example"})
    assert invalid.status_code == 422


def test_invoice_reconciliation_marks_discrepancies(admin_client):
    structure = create_structure(admin_client)
    invoice = admin_client.post(
        "/api/v1/invoices",
        data={
            "number": "FAC-2026-0001",
            "invoice_date": date.today().isoformat(),
            "supplier_id": structure["supplier_id"],
            "notes": "Factura de prueba",
        },
    )
    assert invoice.status_code == 201, invoice.text
    invoice_id = invoice.json()["id"]

    line = admin_client.post(
        f"/api/v1/invoices/{invoice_id}/lines",
        json={
            "product_id": structure["product_id"],
            "description": "Producto de prueba",
            "quantity": "100",
            "unit_price": "10",
            "tax_rate": "21",
        },
    )
    assert line.status_code == 201, line.text
    assert float(line.json()["line_total"]) == 1210.0
    line_id = line.json()["id"]

    reception = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "reception",
            "product_id": structure["product_id"],
            "quantity": "80",
            "to_location_id": structure["location_id"],
            "invoice_id": invoice_id,
            "invoice_line_id": line_id,
            "confirm": True,
        },
    )
    assert reception.status_code == 201, reception.text

    reconciled = admin_client.post(f"/api/v1/invoices/{invoice_id}/reconcile")
    assert reconciled.status_code == 200, reconciled.text
    body = reconciled.json()
    assert body["status"] == "discrepancy"
    assert float(body["lines"][0]["received_quantity"]) == 80
    assert body["lines"][0]["review_required"] is True

    detail = admin_client.get(f"/api/v1/invoices/{invoice_id}").json()
    assert detail["supplier_name"] == "Proveedor Test S.L."
    assert float(detail["total"]) == 1210.0


def test_reports_export_respects_permissions(admin_client, worker_client):
    create_structure(admin_client)
    assert worker_client.get("/api/v1/reports/inventory.csv").status_code == 403
    report = admin_client.get("/api/v1/reports/inventory.csv")
    assert report.status_code == 200
    assert "text/csv" in report.headers["content-type"]
    assert "SKU" in report.text


def test_dashboard_returns_real_kpis(admin_client):
    structure = create_structure(admin_client)
    admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "reception",
            "product_id": structure["product_id"],
            "quantity": "12",
            "to_location_id": structure["location_id"],
            "confirm": True,
        },
    )
    dashboard = admin_client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert body["kpis"]["active_products"] == 1
    assert body["kpis"]["locations"] == 1
    assert float(body["kpis"]["total_units"]) == 12
    assert body["kpis"]["occupancy_pct"] == 100.0
    assert len(body["recent_activity"]) == 1


def test_warehouse_layout_and_reports(admin_client):
    """El mapa del almacén y los CSV se generan con datos reales y columnas coherentes."""
    structure = create_structure(admin_client)
    _second_location(admin_client, structure, aisle="P07")

    reception = admin_client.post(
        "/api/v1/movements",
        json={
            "movement_type": "reception",
            "product_id": structure["product_id"],
            "quantity": "10",
            "to_location_id": structure["location_id"],
            "confirm": True,
            "physical_confirmed": True,
        },
    )
    assert reception.status_code == 201, reception.text

    layout = admin_client.get(f"/api/v1/warehouses/{structure['warehouse_id']}/layout")
    assert layout.status_code == 200, layout.text
    body = layout.json()
    assert body["warehouse"]["id"] == structure["warehouse_id"]
    assert any(aisle["aisle"] == "P07" for aisle in body["aisles"])

    inventory = admin_client.get("/api/v1/reports/inventory.csv")
    assert inventory.status_code == 200, inventory.text
    assert inventory.text.startswith("\ufeff")
    lines = inventory.text.strip().splitlines()
    assert lines[0].count(";") == 13
    assert len(lines) == 2  # cabecera + la única posición con stock del escenario
    columns = lines[1].split(";")
    assert columns[0] == admin_client.get(f"/api/v1/products/{structure['product_id']}").json()["sku"]
    assert columns[9] == "10.000"  # disponible
    assert columns[12].replace(",", ".") == format(10 * float(columns[10]), ".2f")

    movements = admin_client.get("/api/v1/reports/movements.csv")
    assert movements.status_code == 200, movements.text
    header = movements.text.strip().splitlines()[0]
    assert "Referencia" in header and "Confirmación física" in header

    summary = admin_client.get("/api/v1/reports/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["categories"]
