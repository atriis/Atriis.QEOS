"""Sending email, for every service that needs it (auth: verification and reset links;
ingestion: failure notifications). Settings are the SMTP_* fields of BaseServiceSettings."""
import smtplib
from email.headerregistry import Address
from email.message import EmailMessage
from typing import Iterable

TIMEOUT_SECONDS = 10.0


class MailNotConfigured(Exception):
    """SMTP_HOST is empty, or the server needs a sign-in and the credentials are missing: nothing can be sent."""


def mail_configured(settings) -> bool:
    return bool(settings.SMTP_HOST) and not missing_login(settings)


def missing_login(settings) -> bool:
    """The server takes signed-in mail only (SMTP_REQUIRE_LOGIN) and SMTP_USER or SMTP_PASSWORD is empty."""
    return bool(getattr(settings, "SMTP_REQUIRE_LOGIN", False)) and not (settings.SMTP_USER and settings.SMTP_PASSWORD)


def _single_line(text: str) -> str:
    # A CR or LF in a header would let text become a header of its own (Bcc: …)
    return " ".join(str(text).splitlines()).strip()


def send_mail(settings, to: Iterable[str], subject: str, body: str) -> None:
    """Send one plain-text message to every address in `to`. Raises MailNotConfigured without
    SMTP_HOST, and smtplib/OSError exceptions when the server refuses or cannot be reached."""
    if not mail_configured(settings):
        raise MailNotConfigured("SMTP is not configured on this server")
    message = EmailMessage()
    message["Subject"] = _single_line(subject)
    sender = settings.EMAILS_FROM_EMAIL or "no-reply@example.com"
    name = _single_line(getattr(settings, "EMAILS_FROM_NAME", "") or "")
    message["From"] = str(Address(display_name=name, addr_spec=sender)) if name else sender
    message["To"] = ", ".join(_single_line(address) for address in to)
    message.set_content(body)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=TIMEOUT_SECONDS) as server:
        if settings.SMTP_TLS:
            server.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(message)
