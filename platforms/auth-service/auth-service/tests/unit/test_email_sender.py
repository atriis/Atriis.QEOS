import logging
from unittest.mock import MagicMock, patch

from src.auth.config import settings
from src.auth.service.email_sender import EmailSender


def test_logs_the_link_when_smtp_is_not_configured(caplog, monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    with caplog.at_level(logging.INFO):
        EmailSender.send_verification_email(
            "person@example.com", "http://example.com/verify?token=abc"
        )
    assert "http://example.com/verify?token=abc" in caplog.text
    assert "person@example.com" in caplog.text
    # WARNING, not INFO: Python's root logger defaults to WARNING, so an INFO
    # line never reaches the container log — the one place this link must appear
    assert all(r.levelno >= logging.WARNING for r in caplog.records)


def test_logs_the_link_when_the_server_requires_login_and_credentials_are_missing(caplog, monkeypatch):
    # Azure Communication Services with smtp-user/smtp-password not yet in Key Vault: sending would be refused
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.azurecomm.net")
    monkeypatch.setattr(settings, "SMTP_REQUIRE_LOGIN", True)
    monkeypatch.setattr(settings, "SMTP_USER", "")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "")
    with patch("qeos_shared.mail.smtplib.SMTP") as mock_smtp, caplog.at_level(logging.INFO):
        EmailSender.send_password_reset_email("person@example.com", "http://example.com/reset?token=abc", 30)
    mock_smtp.assert_not_called()
    assert "http://example.com/reset?token=abc" in caplog.text
    assert "SMTP credentials missing" in caplog.text
    assert all(r.levelno >= logging.WARNING for r in caplog.records)


def test_sends_without_login_when_the_server_does_not_require_it(monkeypatch):
    # Compose's Mailpit: a host, no credentials, SMTP_REQUIRE_LOGIN off
    monkeypatch.setattr(settings, "SMTP_HOST", "mailpit")
    monkeypatch.setattr(settings, "SMTP_REQUIRE_LOGIN", False)
    monkeypatch.setattr(settings, "SMTP_USER", "")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "")
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server
    with patch("qeos_shared.mail.smtplib.SMTP", return_value=mock_server):
        EmailSender.send_verification_email("person@example.com", "http://example.com/verify?token=abc")
    mock_server.login.assert_not_called()
    mock_server.send_message.assert_called_once()


def test_sends_via_smtp_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_TLS", True)
    monkeypatch.setattr(settings, "SMTP_USER", "user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "pass")
    monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "no-reply@example.com")

    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server
    with patch(
        "qeos_shared.mail.smtplib.SMTP", return_value=mock_server
    ) as mock_smtp:
        EmailSender.send_verification_email(
            "person@example.com", "http://example.com/verify?token=abc"
        )

    mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=10.0)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("user", "pass")
    mock_server.send_message.assert_called_once()
    sent_message = mock_server.send_message.call_args[0][0]
    assert sent_message["To"] == "person@example.com"
    assert "http://example.com/verify?token=abc" in sent_message.get_content()
