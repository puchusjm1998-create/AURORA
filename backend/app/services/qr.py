"""QR payload conventions and PNG rendering.

Payload format: ``aurora://<kind>/<code>``. The scanner understands these
payloads, and the same string is rendered on printable labels.
"""

from __future__ import annotations

import io
from enum import StrEnum

import qrcode
from qrcode.constants import ERROR_CORRECT_M


class QRKind(StrEnum):
    PRODUCT = "product"
    PALLET = "pallet"
    UNIT = "unit"
    LOCATION = "location"
    MOVEMENT = "movement"
    EMPLOYEE = "employee"


def build_payload(kind: QRKind, code: str) -> str:
    return f"aurora://{kind.value}/{code}"


def parse_payload(payload: str) -> tuple[str, str] | None:
    if not payload.startswith("aurora://"):
        return None
    rest = payload[len("aurora://"):]
    if "/" not in rest:
        return None
    kind, code = rest.split("/", 1)
    if kind not in QRKind._value2member_map_ or not code:
        return None
    return kind, code


def render_png(payload: str, *, box_size: int = 8, border: int = 2) -> bytes:
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=box_size, border=border)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
