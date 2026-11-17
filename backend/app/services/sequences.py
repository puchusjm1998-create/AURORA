"""Non-reusable human-readable identifiers (AUR-PAL-*, AUR-OBJ-*, ...)."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CodeSequence

SEQUENCES = {
    "pallet": ("AUR-PAL", 6),
    "unit": ("AUR-OBJ", 6),
    "movement": ("AUR-MOV", 6),
    "employee": ("AUR-EMP", 6),
    "product": ("AUR-SKU", 6),
    "delivery": ("AUR-DEL", 6),
    "task": ("AUR-TSK", 6),
    "incident": ("AUR-INC", 6),
}


def next_code(db: Session, name: str) -> str:
    prefix, width = SEQUENCES[name]
    for attempt in range(3):
        seq = db.get(CodeSequence, name, with_for_update=True)
        if seq is None:
            seq = CodeSequence(name=name, prefix=prefix, next_value=1, width=width)
            db.add(seq)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                continue
        value = seq.next_value
        seq.next_value = value + 1
        db.flush()
        return f"{seq.prefix}-{value:0{seq.width}d}"
    raise RuntimeError(f"No se pudo generar el código de secuencia '{name}'")


def peek_next_code(db: Session, name: str) -> str:
    prefix, width = SEQUENCES[name]
    seq = db.get(CodeSequence, name)
    value = seq.next_value if seq else 1
    actual_prefix = seq.prefix if seq else prefix
    return f"{actual_prefix}-{value:0{width}d}"
