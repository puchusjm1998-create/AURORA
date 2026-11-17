"""Test fixtures.

A fresh SQLite database is created for every test. The application modules are
imported only after the test environment variables are set, so the engine and
settings point at the isolated test database.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_DIR = Path(tempfile.mkdtemp(prefix="aurora-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_DIR / 'test.db').as_posix()}"
os.environ["AURORA_BOOTSTRAP"] = "false"
os.environ["JWT_SECRET"] = "test-secret-aurora-0123456789abcdef0123456789"
os.environ["COOKIE_SECURE"] = "false"
os.environ["ENVIRONMENT"] = "test"
os.environ["STORAGE_DIR"] = str(TEST_DIR / "storage")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.permissions import seed_rbac  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.triggers import install_immutability_triggers  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Role, User  # noqa: E402

PASSWORD = "TestPass123"


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    install_immutability_triggers(engine)
    session = SessionLocal()
    seed_rbac(session)
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _make_user(session, email: str, level: int, full_name: str = "Usuario Prueba") -> User:
    role = session.query(Role).filter(Role.level == level).one()
    existing = session.query(User).filter(User.email == email).one_or_none()
    if existing:
        return existing
    user = User(
        email=email,
        full_name=full_name,
        hashed_password=hash_password(PASSWORD),
        role_id=role.id,
        must_change_password=False,
    )
    session.add(user)
    session.commit()
    return user


@pytest.fixture()
def users(db):
    return {
        "admin": _make_user(db, "admin@test.local", 1, "Admin Prueba"),
        "manager": _make_user(db, "manager@test.local", 2, "Logística Prueba"),
        "supervisor": _make_user(db, "supervisor@test.local", 3, "Encargado Prueba"),
        "worker": _make_user(db, "worker@test.local", 4, "Operario Prueba"),
        "auditor": _make_user(db, "auditor@test.local", 5, "Auditor Prueba"),
    }


def login(client: TestClient, email: str) -> TestClient:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture()
def admin_client(users) -> TestClient:
    return login(TestClient(app), "admin@test.local")


@pytest.fixture()
def worker_client(users) -> TestClient:
    return login(TestClient(app), "worker@test.local")


@pytest.fixture()
def auditor_client(users) -> TestClient:
    return login(TestClient(app), "auditor@test.local")


def create_structure(admin_client: TestClient, *, tracking_mode: str = "quantity") -> dict:
    """Create warehouse, location, supplier and product; return the ids."""
    warehouse = admin_client.post(
        "/api/v1/warehouses",
        json={"code": "ALM-01", "name": "Almacén Test", "city": "Cartagena", "country": "ES"},
    )
    assert warehouse.status_code == 201, warehouse.text
    warehouse_id = warehouse.json()["id"]

    location = admin_client.post(
        "/api/v1/locations",
        json={
            "warehouse_id": warehouse_id,
            "aisle": "P04",
            "rack": "EB",
            "level": "N02",
            "position": "POS03",
            "capacity_pallets": 2,
        },
    )
    assert location.status_code == 201, location.text
    location_id = location.json()["id"]
    assert location.json()["full_code"] == "ALM-01-P04-EB-N02-POS03"

    supplier = admin_client.post(
        "/api/v1/suppliers", json={"name": "Proveedor Test S.L.", "tax_id": "B00000000"}
    )
    assert supplier.status_code == 201, supplier.text

    product = admin_client.post(
        "/api/v1/products",
        json={
            "name": "Producto de prueba",
            "category": "Test",
            "supplier_id": supplier.json()["id"],
            "uom": "ud",
            "purchase_price": "10.00",
            "unit_price": "15.00",
            "min_stock": "5",
            "tracking_mode": tracking_mode,
        },
    )
    assert product.status_code == 201, product.text

    return {
        "warehouse_id": warehouse_id,
        "location_id": location_id,
        "supplier_id": supplier.json()["id"],
        "product_id": product.json()["id"],
        "sku": product.json()["sku"],
        "location_code": location.json()["full_code"],
    }
