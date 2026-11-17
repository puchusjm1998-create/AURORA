#!/usr/bin/env python3
"""Create a DEMONSTRATION dataset in an empty AURORA database.

This script never runs automatically and refuses to run against a production
environment or a database that already contains data. Demonstration data lives
in its own database file (see docs/DEPLOYMENT.md) so it can never be confused
with real warehouse data.

Usage:
    python -m scripts.seed_demo --yes            # empty DB, demo_mode=true
    python -m scripts.seed_demo --yes --force    # allow demo_mode=false (staging only)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.enums import (  # noqa: E402
    AttendanceEventType,
    DeliveryStatus,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    MovementType,
    PalletStatus,
    TaskStatus,
    TrackingMode,
)
from app.core.permissions import seed_rbac  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.timeutils import MADRID  # noqa: E402
from app.db.triggers import install_immutability_triggers  # noqa: E402
from app.models import (  # noqa: E402
    AttendanceRecord,
    Delivery,
    DeliveryPallet,
    Employee,
    Incident,
    Invoice,
    InvoiceLine,
    Location,
    Pallet,
    PalletItem,
    Product,
    Role,
    StockMovement,
    Supplier,
    Task,
    User,
    Vehicle,
    Warehouse,
)
from app.services.sequences import next_code  # noqa: E402
from app.services.stock import StockEngine  # noqa: E402

DEMO_PASSWORD = "Aurora2026!"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def build(args: argparse.Namespace) -> None:
    settings = get_settings()
    if settings.is_production:
        fail("No se pueden cargar datos de demostración en producción.")
    if not settings.demo_mode and not args.force:
        fail(
            "DEMO_MODE no está activo. Arranque con DEMO_MODE=true o use --force "
            "en un entorno de pruebas no productivo."
        )

    # Apply the same versioned migrations used by the API bootstrap so the
    # demonstration database is structurally identical to production.
    from app.db.init import run_migrations

    run_migrations()
    install_immutability_triggers(engine)

    with SessionLocal() as db:
        seed_rbac(db)
        db.commit()

        if db.scalars(select(Warehouse)).first() is not None:
            fail("La base de datos ya contiene datos. Use una base de datos vacía para la demo.")

        admin_role = db.scalars(select(Role).where(Role.level == 1)).one()
        admin = User(
            email="admin@aurora.demo",
            full_name="Elena Navarro",
            hashed_password=hash_password(DEMO_PASSWORD),
            role_id=admin_role.id,
            must_change_password=False,
        )
        db.add(admin)
        db.flush()

        # -- Warehouse and locations -------------------------------------
        warehouse = Warehouse(
            code="ALM-01",
            name="Centro logístico Cartagena",
            address="Polígono industrial Los Camachos, nave 12",
            city="Cartagena",
            postal_code="30390",
            country="ES",
            timezone="Europe/Madrid",
        )
        db.add(warehouse)
        db.flush()

        locations: dict[str, Location] = {}
        for aisle in ["P01", "P02", "P03"]:
            for rack in ["EA", "EB"]:
                for level in ["N01", "N02"]:
                    for position in ["POS01", "POS02", "POS03"]:
                        code = f"{warehouse.code}-{aisle}-{rack}-{level}-{position}"
                        location = Location(
                            warehouse_id=warehouse.id,
                            aisle=aisle,
                            rack=rack,
                            level=level,
                            position=position,
                            full_code=code,
                            label=f"Pasillo {aisle} · {rack} · {level} · {position}",
                            capacity_pallets=2 if position == "POS01" else 1,
                            is_pick_face=level == "N01" and position == "POS01",
                        )
                        db.add(location)
                        locations[code] = location
        db.flush()

        # -- Suppliers ---------------------------------------------------
        suppliers = [
            Supplier(name="Suministros Levante S.L.", tax_id="B30123456", contact_name="Marta Ruiz",
                     email="compras@levante.demo", phone="+34 968 000 111"),
            Supplier(name="TecnoPack Ibérica", tax_id="B30234567", contact_name="Javier Soto",
                     email="pedidos@tecnopack.demo", phone="+34 961 000 222"),
            Supplier(name="Ferretería Industrial Sur", tax_id="B30345678", contact_name="Lucía Pérez",
                     email="ventas@fisur.demo", phone="+34 950 000 333"),
        ]
        db.add_all(suppliers)
        db.flush()

        # -- Employees and accounts --------------------------------------
        people = [
            ("Elena", "Navarro", "Dirección", "Administradora principal", 1, "admin@aurora.demo"),
            ("Sergio", "Martínez", "Logística", "Responsable de logística", 2, "logistica@aurora.demo"),
            ("Carmen", "López", "Almacén", "Encargada de turno", 3, "encargado@aurora.demo"),
            ("Ahmed", "Ben Salah", "Almacén", "Operario de almacén", 4, "operario@aurora.demo"),
            ("Nuria", "García", "Calidad", "Auditora interna", 5, "auditor@aurora.demo"),
            ("Pablo", "Fernández", "Almacén", "Carretillero", 4, "pablo@aurora.demo"),
            ("Inés", "Torres", "Administración", "Administrativa", 4, "ines@aurora.demo"),
            ("Diego", "Romero", "Almacén", "Operario de almacén", 4, "diego@aurora.demo"),
        ]
        employees: dict[str, Employee] = {}
        users: dict[str, User] = {"admin@aurora.demo": admin}
        roles = {role.level: role for role in db.scalars(select(Role)).all()}
        for first, last, department, position, level, email in people:
            employee = Employee(
                code=next_code(db, "employee"),
                first_name=first,
                last_name=last,
                department=department,
                position=position,
                hire_date=date.today() - timedelta(days=400 + level * 30),
                phone=f"+34 600 000 {level}{len(employees):02d}",
            )
            db.add(employee)
            db.flush()
            employees[email] = employee
            user = users.get(email)
            if user is None:
                user = User(
                    email=email,
                    full_name=f"{first} {last}",
                    hashed_password=hash_password(DEMO_PASSWORD),
                    role_id=roles[level].id,
                    must_change_password=False,
                )
                db.add(user)
                db.flush()
                users[email] = user
            employee.user_id = user.id
            if email == "admin@aurora.demo":
                admin.employee = employee
        db.flush()

        # -- Catalogue ---------------------------------------------------
        product_specs = [
            ("Tornillo hexagonal M8 x 40 mm (caja 100 ud.)", "Ferretería", "FIS-8842", "caja", "quantity", 3, "12.40", "19.90", 20, suppliers[2]),
            ("Guantes anticorte nivel 5", "EPI", "LEV-2201", "par", "quantity", 4, "2.15", "4.50", 120, suppliers[0]),
            ("Film retráctil 500 mm x 23 µm", "Embalaje", "TPK-0500", "rollo", "quantity", 2, "6.80", "11.20", 30, suppliers[1]),
            ("Caja cartón doble canal 400x300x200", "Embalaje", "TPK-4030", "ud", "quantity", 6, "0.72", "1.35", 200, suppliers[1]),
            ("Etiquetas térmicas 100x150", "Embalaje", "TPK-1015", "rollo", "quantity", 2, "4.10", "7.60", 25, suppliers[1]),
            ("Carretilla manual 2,5 t", "Equipamiento", "LEV-CT25", "ud", "unit", 1, "285.00", "460.00", 1, suppliers[0]),
            ("Lector de códigos 2D industrial", "Tecnología", "TEC-2D01", "ud", "unit", 1, "148.50", "245.00", 2, suppliers[1]),
            ("Batería litio 48V repuesto carretilla", "Equipamiento", "TEC-BAT48", "ud", "batch", 1, "620.00", "980.00", 1, suppliers[1]),
            ("Aceite hidráulico ISO VG46 (garrafa 20 L)", "Mantenimiento", "FIS-VG46", "garrafa", "batch", 1, "38.75", "62.00", 4, suppliers[2]),
            ("Cinta adhesiva impresa 50 mm", "Embalaje", "TPK-C50", "rollo", "quantity", 4, "0.95", "1.90", 60, suppliers[1]),
            ("Cascos de seguridad EN397", "EPI", "LEV-3970", "ud", "quantity", 3, "4.20", "8.40", 40, suppliers[0]),
            ("Palets Europeos 1200x800", "Embalaje", "LEV-EUR1", "ud", "quantity", 5, "9.50", "15.00", 50, suppliers[0]),
            ("Contenedor plástico plegable 600x400", "Embalaje", "TPK-CP64", "ud", "quantity", 4, "7.30", "13.50", 40, suppliers[1]),
            ("Chaleco reflectante alta visibilidad", "EPI", "LEV-CHV2", "ud", "quantity", 2, "3.60", "7.20", 50, suppliers[0]),
        ]
        products: dict[str, Product] = {}
        for name, category, ref, uom, mode, min_stock, purchase, sale, _qty, supplier in product_specs:
            product = Product(
                sku=next_code(db, "product"),
                name=name,
                description=f"Referencia de demostración {ref}.",
                category=category,
                manufacturer_ref=ref,
                supplier_id=supplier.id,
                uom=uom,
                tracking_mode=TrackingMode(mode),
                min_stock=Decimal(str(min_stock)),
                purchase_price=Decimal(purchase),
                unit_price=Decimal(sale),
            )
            db.add(product)
            db.flush()
            products[ref] = product
        db.commit()

        # -- Invoices -----------------------------------------------------
        invoice_a = Invoice(
            number="LEV-2026/0412",
            supplier_id=suppliers[0].id,
            invoice_date=date.today() - timedelta(days=6),
            subtotal=Decimal("0"),
            tax_total=Decimal("0"),
            total=Decimal("0"),
            uploaded_by=admin.id,
            notes="Factura de demostración conciliada al completo.",
        )
        invoice_b = Invoice(
            number="TPK-2026/1180",
            supplier_id=suppliers[1].id,
            invoice_date=date.today() - timedelta(days=2),
            subtotal=Decimal("0"),
            tax_total=Decimal("0"),
            total=Decimal("0"),
            uploaded_by=admin.id,
            notes="Factura de demostración con una línea pendiente de recepción.",
        )
        db.add_all([invoice_a, invoice_b])
        db.flush()

        def add_line(invoice: Invoice, product: Product, qty: str, price: str, number: int) -> InvoiceLine:
            line = InvoiceLine(
                invoice_id=invoice.id,
                line_number=number,
                product_id=product.id,
                supplier_ref=product.manufacturer_ref,
                description=product.name,
                quantity=Decimal(qty),
                unit_price=Decimal(price),
                line_total=Decimal("0"),
            )
            db.add(line)
            db.flush()
            return line

        line_a1 = add_line(invoice_a, products["LEV-2201"], "800", "2.15", 1)
        line_a2 = add_line(invoice_a, products["LEV-3970"], "120", "4.20", 2)
        line_a3 = add_line(invoice_a, products["LEV-EUR1"], "100", "9.50", 3)
        line_b1 = add_line(invoice_b, products["TPK-0500"], "120", "6.80", 1)
        line_b2 = add_line(invoice_b, products["TPK-4030"], "400", "0.72", 2)
        for invoice in (invoice_a, invoice_b):
            subtotal = sum((l.quantity * l.unit_price for l in invoice.lines), Decimal("0"))
            invoice.subtotal = subtotal
            invoice.tax_total = (subtotal * Decimal("0.21")).quantize(Decimal("0.01"))
            invoice.total = invoice.subtotal + invoice.tax_total
        db.commit()

        # -- Pallet A (conciliated invoice) ------------------------------
        admin = users["admin@aurora.demo"]
        stock = StockEngine(db)
        worker = employees["operario@aurora.demo"]
        supervisor = users["encargado@aurora.demo"]

        pallet_a = Pallet(
            code=next_code(db, "pallet"),
            warehouse_id=warehouse.id,
            location_id=locations["ALM-01-P01-EA-N01-POS02"].id,
            invoice_id=invoice_a.id,
            created_by=admin.id,
            notes="Recepción factura LEV-2026/0412",
        )
        db.add(pallet_a)
        db.flush()

        pallet_contents = [
            (products["LEV-2201"], "800", line_a1.id, None, None),
            (products["LEV-3970"], "120", line_a2.id, None, None),
            (products["LEV-EUR1"], "100", line_a3.id, None, None),
        ]
        for product, qty, line_id, batch, serials in pallet_contents:
            movement = stock.create_movement(
                actor=admin,
                movement_type=MovementType.RECEPTION,
                product_id=product.id,
                quantity=qty,
                to_location_id=pallet_a.location_id,
                to_pallet_id=pallet_a.id,
                worker_id=worker.id,
                invoice_id=invoice_a.id,
                invoice_line_id=line_id,
                reason="Recepción de mercancía de proveedor",
                document_ref=invoice_a.number,
                confirm=True,
                physical_confirmed=True,
            )
            pallet_a.items.append(PalletItem(product_id=product.id, quantity=Decimal(qty)))
            _ = movement
        db.flush()
        stock.seal_pallet(pallet_a, actor=supervisor)
        db.commit()

        # -- Pallet B (unit-tracked + batch) -----------------------------
        pallet_b = Pallet(
            code=next_code(db, "pallet"),
            warehouse_id=warehouse.id,
            location_id=locations["ALM-01-P02-EB-N01-POS01"].id,
            created_by=admin.id,
            notes="Equipamiento con seguimiento unitario",
        )
        db.add(pallet_b)
        db.flush()
        stock.create_movement(
            actor=admin,
            movement_type=MovementType.RECEPTION,
            product_id=products["LEV-CT25"].id,
            quantity="1",
            to_location_id=pallet_b.location_id,
            to_pallet_id=pallet_b.id,
            worker_id=worker.id,
            unit_serials=["CT25-2026-0001"],
            reason="Recepción de equipamiento",
            confirm=True,
            physical_confirmed=True,
        )
        pallet_b.items.append(PalletItem(product_id=products["LEV-CT25"].id, quantity=Decimal("1")))
        db.flush()
        stock.seal_pallet(pallet_b, actor=supervisor)
        db.commit()

        # -- Pallet C (batch tracked) ------------------------------------
        pallet_c = Pallet(
            code=next_code(db, "pallet"),
            warehouse_id=warehouse.id,
            location_id=locations["ALM-01-P03-EA-N02-POS02"].id,
            created_by=admin.id,
            notes="Lote de mantenimiento",
        )
        db.add(pallet_c)
        db.flush()
        stock.create_movement(
            actor=admin,
            movement_type=MovementType.RECEPTION,
            product_id=products["FIS-VG46"].id,
            quantity="24",
            to_location_id=pallet_c.location_id,
            to_pallet_id=pallet_c.id,
            worker_id=worker.id,
            batch_code="VG46-2026-A",
            reason="Recepción de lote de mantenimiento",
            confirm=True,
            physical_confirmed=True,
        )
        pallet_c.items.append(
            PalletItem(
                product_id=products["FIS-VG46"].id,
                quantity=Decimal("24"),
                batch_code="VG46-2026-A",
            )
        )
        db.flush()
        stock.seal_pallet(pallet_c, actor=supervisor)
        db.commit()

        # -- Pallet D (invoice B, partially received) --------------------
        pallet_d = Pallet(
            code=next_code(db, "pallet"),
            warehouse_id=warehouse.id,
            location_id=locations["ALM-01-P02-EA-N02-POS03"].id,
            invoice_id=invoice_b.id,
            created_by=admin.id,
            notes="Recepción parcial factura TPK-2026/1180",
        )
        db.add(pallet_d)
        db.flush()
        for product, qty, line_id in [
            (products["TPK-0500"], "120", line_b1.id),
            (products["TPK-4030"], "280", line_b2.id),
        ]:
            stock.create_movement(
                actor=admin,
                movement_type=MovementType.RECEPTION,
                product_id=product.id,
                quantity=qty,
                to_location_id=pallet_d.location_id,
                to_pallet_id=pallet_d.id,
                worker_id=worker.id,
                invoice_id=invoice_b.id,
                invoice_line_id=line_id,
                reason="Recepción parcial de factura",
                document_ref=invoice_b.number,
                confirm=True,
                physical_confirmed=True,
            )
            pallet_d.items.append(PalletItem(product_id=product.id, quantity=Decimal(qty)))
        db.flush()
        stock.seal_pallet(pallet_d, actor=supervisor)
        db.commit()

        # -- Bulk stock in pick faces (no pallet) ------------------------
        bulk = [
            ("FIS-8842", "60", "ALM-01-P01-EA-N01-POS01"),
            ("TPK-C50", "180", "ALM-01-P01-EB-N01-POS01"),
            ("LEV-3970", "30", "ALM-01-P01-EA-N02-POS01"),
            ("TPK-1015", "18", "ALM-01-P02-EA-N01-POS01"),
            ("LEV-CHV2", "75", "ALM-01-P02-EB-N02-POS01"),
        ]
        for ref, qty, location_code in bulk:
            stock.create_movement(
                actor=admin,
                movement_type=MovementType.RECEPTION,
                product_id=products[ref].id,
                quantity=qty,
                to_location_id=locations[location_code].id,
                worker_id=worker.id,
                reason="Estocaje en ubicación de picking",
                confirm=True,
                physical_confirmed=True,
            )
        db.commit()

        # -- Internal moves, picking and a shipment ----------------------
        stock.create_movement(
            actor=supervisor,
            movement_type=MovementType.INTERNAL_MOVE,
            product_id=products["FIS-8842"].id,
            quantity="20",
            from_location_id=locations["ALM-01-P01-EA-N01-POS01"].id,
            to_location_id=locations["ALM-01-P03-EA-N01-POS02"].id,
            worker_id=employees["pablo@aurora.demo"].id,
            reason="Reposición de pasillo 3",
            confirm=True,
            physical_confirmed=True,
        )
        shipment = stock.create_movement(
            actor=supervisor,
            movement_type=MovementType.SHIPMENT,
            product_id=products["TPK-C50"].id,
            quantity="40",
            from_location_id=locations["ALM-01-P01-EB-N01-POS01"].id,
            worker_id=employees["diego@aurora.demo"].id,
            reason="Pedido cliente DEMO-1042",
            document_ref="ALBARAN-DEMO-1042",
            confirm=True,
            physical_confirmed=True,
        )
        _ = shipment
        db.commit()

        # -- Active reservation ------------------------------------------
        stock.reserve(
            product_id=products["TPK-4030"].id,
            location_id=locations["ALM-01-P02-EA-N02-POS03"].id,
            pallet_id=pallet_d.id,
            quantity=Decimal("40"),
            reference="PEDIDO-DEMO-2031",
            actor=supervisor,
        )
        db.commit()

        # -- Warehouse tasks ---------------------------------------------
        now = datetime.now(timezone.utc)
        task_specs = [
            (
                "Preparar pedido PEDIDO-DEMO-2031",
                "Recoger 40 cajas del palé AUR-PAL-000004 y dejarlas en el muelle de salida.",
                1,
                "diego@aurora.demo",
                TaskStatus.PENDING,
                now + timedelta(hours=3),
                None,
            ),
            (
                "Recuento cíclico del pasillo P02",
                "Verificar existencias físicas de las posiciones P02 y anotar diferencias antes del cierre.",
                2,
                "pablo@aurora.demo",
                TaskStatus.IN_PROGRESS,
                now + timedelta(hours=6),
                None,
            ),
            (
                "Revisar discrepancias de la factura TPK-2026/1181",
                "Contrastar las líneas pendientes con las recepciones físicas y documentar la diferencia.",
                2,
                "encargado@aurora.demo",
                TaskStatus.PENDING,
                now + timedelta(days=1),
                None,
            ),
            (
                "Reubicar mercancía al picking de P01",
                "Mover 20 cajas de FIS-8842 desde la reserva al hueco de picking.",
                3,
                "operario@aurora.demo",
                TaskStatus.PENDING,
                now + timedelta(days=1, hours=2),
                None,
            ),
            (
                "Precintar palé de devoluciones",
                "Comprobado y precintado el palé de devoluciones del turno de mañana.",
                4,
                "pablo@aurora.demo",
                TaskStatus.DONE,
                now - timedelta(hours=2),
                now - timedelta(hours=1),
            ),
        ]
        for title, description, priority, email, status, due_at, completed_at in task_specs:
            db.add(
                Task(
                    code=next_code(db, "task"),
                    title=title,
                    description=description,
                    priority=priority,
                    assigned_to=employees[email].id,
                    status=status,
                    due_at=due_at,
                    completed_at=completed_at,
                    created_by=supervisor.id,
                )
            )
        db.commit()

        # -- Incidents -----------------------------------------------------
        incident_specs = [
            (
                "Derrame de líquido en el pasillo P01",
                "Una garrafa ha goteado junto a la estantería. Zona señalizada y absorbente colocado.",
                IncidentType.SAFETY,
                IncidentSeverity.CRITICAL,
                IncidentStatus.OPEN,
                "pablo@aurora.demo",
                locations["ALM-01-P01-EA-N01-POS01"].id,
                None,
                None,
                "",
                None,
            ),
            (
                "Palé con esquina dañada en recepción",
                "Dos cajas de tornillería presentan golpes; el palé no es estable para almacenar.",
                IncidentType.DAMAGE,
                IncidentSeverity.HIGH,
                IncidentStatus.ACKNOWLEDGED,
                "operario@aurora.demo",
                None,
                products["FIS-8842"].id,
                pallet_d.id,
                "",
                None,
            ),
            (
                "Descuadre de 2 cajas en el recuento de TPK-0500",
                "El sistema indica 120 cajas y el recuento físico da 118.",
                IncidentType.DISCREPANCY,
                IncidentSeverity.MEDIUM,
                IncidentStatus.RESOLVED,
                "diego@aurora.demo",
                None,
                products["TPK-0500"].id,
                None,
                "Se localizaron las dos cajas en el hueco contiguo y se registró un movimiento de corrección.",
                now - timedelta(days=1),
            ),
            (
                "Etiqueta QR ilegible en una ubicación",
                "La etiqueta de la posición P03 estaba despegada y no se podía escanear.",
                IncidentType.QUALITY,
                IncidentSeverity.LOW,
                IncidentStatus.CLOSED,
                None,
                locations["ALM-01-P03-EA-N01-POS02"].id,
                None,
                None,
                "Se reimprimió la etiqueta y se fijó con funda protectora.",
                now - timedelta(days=3),
            ),
        ]
        for title, description, kind, severity, status, email, location_id, product_id, pallet_id, resolution, resolved_at in incident_specs:
            db.add(
                Incident(
                    code=next_code(db, "incident"),
                    title=title,
                    description=description,
                    incident_type=kind,
                    severity=severity,
                    status=status,
                    reported_by=supervisor.id,
                    assigned_to=employees[email].id if email else None,
                    location_id=location_id,
                    product_id=product_id,
                    pallet_id=pallet_id,
                    resolution=resolution,
                    resolved_at=resolved_at,
                )
            )
        db.commit()

        # -- Attendance ----------------------------------------------------
        def punch(email: str, event: AttendanceEventType, moment: datetime) -> None:
            db.add(
                AttendanceRecord(
                    employee_id=employees[email].id,
                    event_type=event,
                    occurred_at=moment.astimezone(timezone.utc),
                    source="web",
                    note="",
                    created_by=employees[email].user_id,
                )
            )

        now_naive = datetime.now(MADRID).replace(tzinfo=MADRID)
        today_local = now_naive.date()
        yesterday_local = today_local - timedelta(days=1)
        for email in ("pablo@aurora.demo", "operario@aurora.demo", "diego@aurora.demo", "encargado@aurora.demo"):
            base = datetime.combine(yesterday_local, time(6), tzinfo=MADRID)
            punch(email, AttendanceEventType.CLOCK_IN, base)
            punch(email, AttendanceEventType.BREAK_START, base + timedelta(hours=4))
            punch(email, AttendanceEventType.BREAK_END, base + timedelta(hours=4, minutes=20))
            punch(email, AttendanceEventType.CLOCK_OUT, base + timedelta(hours=8))

        punch("pablo@aurora.demo", AttendanceEventType.CLOCK_IN, now_naive - timedelta(hours=4))
        punch("operario@aurora.demo", AttendanceEventType.CLOCK_IN, now_naive - timedelta(hours=5))
        punch("operario@aurora.demo", AttendanceEventType.BREAK_START, now_naive - timedelta(minutes=20))
        punch("diego@aurora.demo", AttendanceEventType.CLOCK_IN, now_naive - timedelta(hours=6))
        punch("diego@aurora.demo", AttendanceEventType.BREAK_START, now_naive - timedelta(hours=2))
        punch("diego@aurora.demo", AttendanceEventType.BREAK_END, now_naive - timedelta(hours=2) + timedelta(minutes=15))
        punch("diego@aurora.demo", AttendanceEventType.CLOCK_OUT, now_naive - timedelta(hours=1))
        punch("encargado@aurora.demo", AttendanceEventType.CLOCK_IN, now_naive - timedelta(hours=3))
        db.commit()

        # -- Vehicles and deliveries ---------------------------------------
        vehicle_a = Vehicle(plate="1234 ABC", model="Iveco Daily 35S14", capacity_kg=Decimal("3500"))
        vehicle_b = Vehicle(plate="5678 DEF", model="Mercedes Sprinter 315", capacity_kg=Decimal("1400"))
        db.add_all([vehicle_a, vehicle_b])
        db.flush()
        delivery_a = Delivery(
            reference=next_code(db, "delivery"),
            vehicle_id=vehicle_a.id,
            driver_employee_id=employees["diego@aurora.demo"].id,
            status=DeliveryStatus.DRAFT,
            destination_name="Cliente Demo Norte S.L.",
            destination_address="Polígono Cabezo Beaza, nave 14, Cartagena",
            planned_departure=now + timedelta(days=1, hours=2),
            notes="Descarga con muelle propio; llamar al llegar.",
            created_by=supervisor.id,
        )
        delivery_b = Delivery(
            reference=next_code(db, "delivery"),
            vehicle_id=vehicle_b.id,
            driver_employee_id=employees["pablo@aurora.demo"].id,
            status=DeliveryStatus.PREPARING,
            destination_name="Ferretería del Puerto",
            destination_address="Calle Real 22, Cartagena",
            planned_departure=now + timedelta(hours=5),
            notes="Entregar antes de las 14:00.",
            created_by=supervisor.id,
        )
        db.add_all([delivery_a, delivery_b])
        db.flush()
        db.add_all(
            [
                DeliveryPallet(delivery_id=delivery_a.id, pallet_id=pallet_c.id),
                DeliveryPallet(delivery_id=delivery_b.id, pallet_id=pallet_b.id),
            ]
        )
        db.commit()

        # -- Invoice reconciliation --------------------------------------
        # Invoice A fully received -> reconciled.
        for line in invoice_a.lines:
            line.received_quantity = line.quantity
            line.review_required = False
        invoice_a.status = "reconciled"
        invoice_a.reconciled_at = datetime.now(timezone.utc)

        # Invoice B: one line pending -> discrepancy requiring review.
        db.flush()
        for line in invoice_b.lines:
            received = sum(
                (
                    movement.quantity
                    for movement in db.scalars(
                        select(StockMovement).where(
                            StockMovement.invoice_line_id == line.id,
                            StockMovement.status == "confirmed",
                        )
                    ).all()
                ),
                Decimal("0"),
            )
            line.received_quantity = received
            line.review_required = received != line.quantity
        invoice_b.status = "discrepancy"
        invoice_b.reconciled_at = datetime.now(timezone.utc)
        db.commit()

        print("\n=== AURORA · datos de DEMOSTRACIÓN cargados ===")
        print(f"Almacén: {warehouse.code} · {warehouse.name}")
        print(
            f"Ubicaciones: {len(locations)} · Productos: {len(products)} · Palés: 4"
            f" · Tareas: {len(task_specs)} · Incidencias: {len(incident_specs)} · Fichajes: 24 · Repartos: 2"
        )
        print("Cuentas (contraseña única de demo):", DEMO_PASSWORD)
        for label, email in [
            ("Nivel 1 Administrador", "admin@aurora.demo"),
            ("Nivel 2 Logística", "logistica@aurora.demo"),
            ("Nivel 3 Encargado", "encargado@aurora.demo"),
            ("Nivel 4 Operario", "operario@aurora.demo"),
            ("Nivel 5 Auditor", "auditor@aurora.demo"),
        ]:
            print(f"  - {label}: {email}")
        print("Base de datos:", settings.database_url)
        print("Estos datos NO son reales y deben permanecer aislados de producción.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga el conjunto de datos de demostración de AURORA.")
    parser.add_argument("--yes", action="store_true", help="Confirma la carga sin preguntar")
    parser.add_argument("--force", action="store_true", help="Permite ejecutar con DEMO_MODE=false")
    args = parser.parse_args()
    if not args.yes:
        print("Este script crea datos de DEMOSTRACIÓN. Confirme con --yes.", file=sys.stderr)
        sys.exit(2)
    build(args)


if __name__ == "__main__":
    main()
