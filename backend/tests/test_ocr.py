"""OCR real de facturas: PDF con texto, imagen escaneada y revisión humana."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from tests.conftest import create_structure

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def invoice_pdf() -> bytes:
    buffer = io.BytesIO()
    document = canvas.Canvas(buffer, pagesize=A4)
    y = 800
    for line in [
        "FERRETERIA DEL PUERTO S.L.",
        "CIF: B12345678",
        "Factura numero: F-2026-0042",
        "Fecha: 12/11/2026",
        "Vencimiento: 12/12/2026",
        "Descripcion                      Cantidad      Precio        Total",
        "Tornillo hexagonal M8                 100        0,25        25,00",
        "Tuerca autoblocante M8                 50        0,40        20,00",
        "Base imponible: 45,00 EUR",
        "IVA 21%: 9,45 EUR",
        "TOTAL: 54,45 EUR",
    ]:
        document.drawString(50, y, line)
        y -= 24
    document.save()
    return buffer.getvalue()


def invoice_image() -> bytes:
    image = Image.new("RGB", (1200, 620), "white")
    draw = ImageDraw.Draw(image)
    normal = ImageFont.truetype(str(FONT), 28)
    title = ImageFont.truetype(str(FONT), 38)
    draw.text((40, 30), "FERRETERIA DEL PUERTO S.L.", fill="black", font=title)
    draw.text((40, 95), "CIF: B12345678", fill="black", font=normal)
    draw.text((40, 145), "Factura numero: F-2026-0042", fill="black", font=normal)
    draw.text((40, 195), "Fecha: 12/11/2026", fill="black", font=normal)
    draw.text((40, 280), "Descripcion          Cantidad     Precio     Total", fill="black", font=normal)
    draw.text((40, 330), "Tornillo hexagonal M8      100     0,25     25,00", fill="black", font=normal)
    draw.text((40, 380), "Tuerca autoblocante M8      50     0,40     20,00", fill="black", font=normal)
    draw.text((40, 480), "Base imponible: 45,00 EUR", fill="black", font=normal)
    draw.text((40, 530), "IVA 21%: 9,45 EUR", fill="black", font=normal)
    draw.text((40, 575), "TOTAL: 54,45 EUR", fill="black", font=title)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_pdf_text_preview_and_reviewed_creation(admin_client):
    structure = create_structure(admin_client)
    preview = admin_client.post(
        "/api/v1/invoices/ocr/preview",
        files={"file": ("factura.pdf", invoice_pdf(), "application/pdf")},
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["status"] == "done"
    assert data["method"] == "pdf_text"
    assert data["supplier_name"].startswith("FERRETERIA DEL PUERTO")
    assert data["supplier_tax_id"] == "B12345678"
    assert data["invoice_number"] == "F-2026-0042"
    assert data["invoice_date"] == "2026-11-12"
    assert data["due_date"] == "2026-12-12"
    assert data["total"] == "54.45"
    assert len(data["lines"]) == 2
    assert data["confidence"] > 0.8
    assert data["human_review_required"] is True

    lines = [
        {
            "description": line["description"],
            "quantity": line["quantity"],
            "unit_price": line["unit_price"],
            "tax_rate": line["tax_rate"],
        }
        for line in data["lines"]
    ]
    created = admin_client.post(
        "/api/v1/invoices",
        data={
            "number": data["invoice_number"],
            "invoice_date": data["invoice_date"],
            "supplier_id": structure["supplier_id"],
            "notes": "Creada desde OCR revisado",
            "lines_json": json.dumps(lines),
            "ocr_reviewed": "true",
        },
        files={"file": ("factura.pdf", invoice_pdf(), "application/pdf")},
    )
    assert created.status_code == 201, created.text
    invoice = created.json()
    assert invoice["ocr_status"] == "done"
    assert len(invoice["lines"]) == 2
    assert invoice["subtotal"] == "45.00"
    assert invoice["tax_total"] == "9.45"
    assert invoice["total"] == "54.45"

    extracted = admin_client.post(f"/api/v1/invoices/{invoice['id']}/extract")
    assert extracted.status_code == 200, extracted.text
    stored = extracted.json()
    assert stored["method"] == "pdf_text"
    assert stored["engine"].startswith("RapidOCR")
    assert stored["warnings"] == []
    assert stored["creator_name"] == "Admin Prueba"
    assert len(stored["lines"]) == 2

    status = admin_client.get(f"/api/v1/invoices/{invoice['id']}/ocr-status").json()
    assert status["details"]["ocr_status"] == "done"
    assert status["details"]["provider_configured"] is True
    assert status["details"]["external_service"] is False


def test_bulk_lines_and_permissions(admin_client, worker_client):
    structure = create_structure(admin_client)
    invoice = admin_client.post(
        "/api/v1/invoices",
        data={
            "number": "MANUAL-1",
            "invoice_date": "2026-11-10",
            "supplier_id": structure["supplier_id"],
        },
    )
    assert invoice.status_code == 201
    invoice_id = invoice.json()["id"]

    bulk = admin_client.post(
        f"/api/v1/invoices/{invoice_id}/lines/bulk",
        json=[
            {"description": "Tornillo M8", "quantity": "100", "unit_price": "0.25"},
            {"description": "Tuerca M8", "quantity": "50", "unit_price": "0.40"},
        ],
    )
    assert bulk.status_code == 200, bulk.text
    assert len(bulk.json()["lines"]) == 2
    assert bulk.json()["subtotal"] == "45.00"

    assert worker_client.post(
        "/api/v1/invoices/ocr/preview",
        files={"file": ("factura.pdf", invoice_pdf(), "application/pdf")},
    ).status_code == 403
    assert admin_client.post(
        "/api/v1/invoices/ocr/preview",
        files={"file": ("factura.txt", b"no permitido", "text/plain")},
    ).status_code == 422


@pytest.mark.skipif(not FONT.exists(), reason="fuente DejaVu no disponible")
def test_image_ocr_extracts_real_text(admin_client):
    create_structure(admin_client)
    preview = admin_client.post(
        "/api/v1/invoices/ocr/preview",
        files={"file": ("factura.png", invoice_image(), "image/png")},
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["method"] == "image_ocr"
    assert data["status"] == "done"
    assert data["invoice_number"] == "F-2026-0042"
    assert data["invoice_date"] == "2026-11-12"
    assert data["total"] == "54.45"
    assert len(data["lines"]) == 2
    assert data["confidence"] > 0.5
    assert "FERRETERIA" in data["raw_text"].upper()
