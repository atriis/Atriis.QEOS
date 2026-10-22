from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from qeos_shared.mail import MailNotConfigured, mail_configured, send_mail


def smtp_settings(**overrides):
    values = dict(SMTP_HOST="smtp.example.com", SMTP_PORT=587, SMTP_TLS=True, SMTP_USER="user",
                  SMTP_PASSWORD="pass", EMAILS_FROM_EMAIL="qa@example.com", EMAILS_FROM_NAME="QEOS")
    values.update(overrides)
    return SimpleNamespace(**values)


def test_sends_one_message_to_every_recipient():
    server = MagicMock()
    server.__enter__.return_value = server
    with patch("qeos_shared.mail.smtplib.SMTP", return_value=server) as smtp:
        send_mail(smtp_settings(), ["a@example.com", "b@example.com"], "Subject", "Body")
    smtp.assert_called_once_with("smtp.example.com", 587, timeout=10.0)
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("user", "pass")
    message = server.send_message.call_args[0][0]
    assert message["To"] == "a@example.com, b@example.com"
    assert message["From"] == "QEOS <qa@example.com>"
    assert message["Subject"] == "Subject" and message.get_content().strip() == "Body"


def test_no_login_without_credentials_and_no_tls_when_off():
    server = MagicMock()
    server.__enter__.return_value = server
    with patch("qeos_shared.mail.smtplib.SMTP", return_value=server):
        send_mail(smtp_settings(SMTP_USER="", SMTP_PASSWORD="", SMTP_TLS=False), ["a@example.com"], "S", "B")
    server.login.assert_not_called()
    server.starttls.assert_not_called()


def test_without_a_host_it_refuses_instead_of_pretending():
    settings = smtp_settings(SMTP_HOST="")
    assert mail_configured(settings) is False
    with pytest.raises(MailNotConfigured):
        send_mail(settings, ["a@example.com"], "S", "B")


@pytest.mark.parametrize("user, password", [("", ""), ("user", ""), ("", "pass")])
def test_a_server_that_requires_login_without_credentials_is_not_configured(user, password):
    settings = smtp_settings(SMTP_REQUIRE_LOGIN=True, SMTP_USER=user, SMTP_PASSWORD=password)
    assert mail_configured(settings) is False
    with pytest.raises(MailNotConfigured):
        send_mail(settings, ["a@example.com"], "S", "B")


def test_a_server_that_requires_login_with_credentials_is_configured():
    assert mail_configured(smtp_settings(SMTP_REQUIRE_LOGIN=True)) is True


def test_header_injection_through_the_subject_is_impossible():
    server = MagicMock()
    server.__enter__.return_value = server
    with patch("qeos_shared.mail.smtplib.SMTP", return_value=server):
        send_mail(smtp_settings(), ["a@example.com"], "Hi\r\nBcc: evil@example.com", "B")
    message = server.send_message.call_args[0][0]
    assert message["Bcc"] is None
