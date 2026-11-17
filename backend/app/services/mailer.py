"""Envío de correo saliente por SMTP para los informes programados.

Sin ``SMTP_HOST`` configurado no se envía nada: la API responde 409
``smtp_not_configured`` y la interfaz lo muestra como pendiente de configurar.
Soporta STARTTLS (por defecto), SSL directo y autenticación opcional.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from app.core.config import Settings, get_settings


class MailNotConfigured(RuntimeError):
    """El despliegue no tiene servidor SMTP configurado."""


class MailDeliveryError(RuntimeError):
    """El servidor SMTP rechazó o no completó el envío."""


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime_type: str


@dataclass
class Message:
    to: list[str]
    subject: str
    body: str
    attachments: list[Attachment] = field(default_factory=list)


def _settings(settings: Settings | None = None) -> Settings:
    return settings or get_settings()


def send(message: Message, *, settings: Settings | None = None) -> str:
    """Envía el mensaje y devuelve su ``Message-ID``."""
    config = _settings(settings)
    if not config.smtp_configured:
        raise MailNotConfigured("No hay servidor SMTP configurado (SMTP_HOST).")

    email = EmailMessage()
    email["From"] = config.smtp_from
    email["To"] = ", ".join(message.to)
    email["Subject"] = message.subject
    email["Date"] = formatdate(localtime=False)
    email["Message-ID"] = make_msgid(domain="aurora.local")
    email.set_content(message.body)
    for attachment in message.attachments:
        maintype, _, subtype = attachment.mime_type.partition("/")
        email.add_attachment(
            attachment.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=attachment.filename,
        )

    context = ssl.create_default_context()
    try:
        if config.smtp_ssl:
            with smtplib.SMTP_SSL(
                config.smtp_host, config.smtp_port, timeout=config.smtp_timeout, context=context
            ) as client:
                if config.smtp_user:
                    client.login(config.smtp_user, config.smtp_password)
                client.send_message(email)
        else:
            with smtplib.SMTP(
                config.smtp_host, config.smtp_port, timeout=config.smtp_timeout
            ) as client:
                client.ehlo()
                if config.smtp_starttls:
                    client.starttls(context=context)
                    client.ehlo()
                if config.smtp_user:
                    client.login(config.smtp_user, config.smtp_password)
                client.send_message(email)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailDeliveryError(f"El servidor SMTP rechazó el envío: {exc}") from exc
    return str(email["Message-ID"])
