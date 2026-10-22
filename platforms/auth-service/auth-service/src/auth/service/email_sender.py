"""Sends the email-verification and password-reset links.

SMTP_HOST and friends already existed in config.py, unread. Unlike Google SSO (which fails
closed with 503 when unconfigured -- verifying without an audience would be a worse hole
than refusing), this cannot fail closed: every development and test environment lacking a
real SMTP server would be unable to register at all, which is unacceptable for a control
this central. When SMTP_HOST is empty (the default), or the server needs a sign-in
(SMTP_REQUIRE_LOGIN) and SMTP_USER or SMTP_PASSWORD is empty, the link is logged instead of sent:
such a server would refuse the message, and the link would be neither sent nor logged.
"""
import logging

from qeos_shared.mail import mail_configured, missing_login, send_mail

from src.auth.config import settings

logger = logging.getLogger(__name__)


def _deliver(to_email: str, subject: str, body: str, kind: str, link: str) -> None:
    if not mail_configured(settings):
        # WARNING, not INFO: the root logger defaults to WARNING, so an INFO
        # line never reaches the container log — and this link is the only
        # way to finish the flow on a deployment without SMTP
        reason = "SMTP credentials missing" if settings.SMTP_HOST and missing_login(settings) else "SMTP not configured"
        logger.warning("%s for %s (%s, logging instead): %s", kind, to_email, reason, link)
        return
    send_mail(settings, [to_email], subject, body)


class EmailSender:
    @staticmethod
    def send_verification_email(to_email: str, verification_link: str) -> None:
        body = (
            f"Click the link below to complete your registration:\n\n{verification_link}\n\n"
            "This link expires in 24 hours."
        )
        _deliver(to_email, "Verify your email", body, "Verification email", verification_link)

    @staticmethod
    def send_password_reset_email(to_email: str, reset_link: str, expire_minutes: int) -> None:
        body = (
            f"Someone asked to reset the password of your QEOS account.\n\n{reset_link}\n\n"
            f"The link works once and expires in {expire_minutes} minutes. If you did not ask "
            "for this, ignore this email: your password stays as it is."
        )
        _deliver(to_email, "Reset your password", body, "Password reset email", reset_link)
