"""Database bootstrap: migrations, reference data and first administrator."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from app.core.config import BACKEND_DIR, get_settings
from app.core.db import SessionLocal, engine
from app.core.permissions import seed_rbac
from app.core.security import hash_password
from app.db.triggers import install_immutability_triggers
from app.models import Role, User

logger = logging.getLogger("aurora.bootstrap")
settings = get_settings()


def run_migrations() -> None:
    """Apply the versioned Alembic migrations."""
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # configparser treats % specially; escape it for URL-encoded passwords.
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def bootstrap_reference_data() -> None:
    with SessionLocal() as db:
        seed_rbac(db)
        db.commit()


def ensure_admin_from_env() -> None:
    import os

    email = (os.getenv("AURORA_ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("AURORA_ADMIN_PASSWORD") or ""
    name = os.getenv("AURORA_ADMIN_NAME") or "Administrador AURORA"
    if not email or not password:
        return
    with SessionLocal() as db:
        existing = db.scalars(select(User).where(User.email == email)).first()
        if existing:
            return
        role = db.scalars(select(Role).where(Role.level == 1)).first()
        if role is None:
            raise RuntimeError("Los roles no están inicializados.")
        try:
            user = User(
                email=email,
                full_name=name,
                hashed_password=hash_password(password),
                role_id=role.id,
                must_change_password=True,
            )
        except ValueError as exc:
            raise RuntimeError(f"AURORA_ADMIN_PASSWORD no cumple la política: {exc}") from exc
        db.add(user)
        db.commit()
        logger.warning("Administrador inicial creado para %s. Cambie la contraseña al acceder.", email)


def initialize_database(*, migrate: bool = True) -> None:
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
    if migrate:
        run_migrations()
        install_immutability_triggers(engine)
    bootstrap_reference_data()
    ensure_admin_from_env()


def create_all_for_tests() -> None:
    """Used only by the automated test-suite (fast, no Alembic)."""
    from app.models import Base

    Base.metadata.create_all(bind=engine)
    install_immutability_triggers(engine)
    bootstrap_reference_data()
