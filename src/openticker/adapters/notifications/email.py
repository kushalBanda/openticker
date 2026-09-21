"""EmailAdapter(NotificationPort): sends through any SMTP server. Hosted
providers (Resend, Amazon SES, Gmail, ...) all offer SMTP, so one adapter
covers them (ADR 10 in docs/adr). Port 465 uses implicit TLS; any other port
upgrades with STARTTLS."""

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

IMPLICIT_TLS_PORT = 465


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str
    sender: str
    recipient: str


class EmailAdapter:
    def __init__(self, settings: SmtpSettings) -> None:
        self._settings = settings

    def send(self, subject: str, message: str) -> None:
        settings = self._settings
        email = EmailMessage()
        email["From"] = settings.sender
        email["To"] = settings.recipient
        email["Subject"] = f"[OpenTicker] {subject}"
        email.set_content(message)
        if settings.port == IMPLICIT_TLS_PORT:
            with smtplib.SMTP_SSL(settings.host, settings.port, timeout=15) as smtp:
                smtp.login(settings.username, settings.password)
                smtp.send_message(email)
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=15) as smtp:
                smtp.starttls()
                smtp.login(settings.username, settings.password)
                smtp.send_message(email)
