"""Sending e-mail over SMTP (a Gmail address with an app password works, and is free)."""

from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from . import config

OUTBOX: list[dict] = []   # in demo mode and tests, messages land here instead of being sent
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}$")


def valid_email(value: str) -> bool:
    return bool(value) and len(value) <= 254 and bool(_EMAIL.match(value))


def configured() -> bool:
    return config.DEMO or bool(config.SMTP_USER and config.SMTP_PASSWORD)


def send(to: str, subject: str, text: str, html: str | None = None, headers: dict | None = None) -> None:
    if not valid_email(to):
        raise ValueError("invalid recipient")
    msg = EmailMessage()
    msg["From"] = formataddr(("Cirrus Weather", config.SMTP_USER or "alerts@cirrus.invalid"))
    msg["To"] = to
    msg["Subject"] = subject            # EmailMessage refuses line breaks in headers, so nothing can be injected
    for key, value in (headers or {}).items():
        msg[key] = value
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    if config.DEMO or not (config.SMTP_USER and config.SMTP_PASSWORD):
        OUTBOX.append({"to": to, "subject": subject, "text": text, "html": html or "", "headers": dict(headers or {})})
        return
    try:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20, context=ssl.create_default_context()) as smtp:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise RuntimeError(f"The mail server refused the message: {exc}") from exc
