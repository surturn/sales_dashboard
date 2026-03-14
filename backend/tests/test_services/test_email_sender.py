from unittest.mock import MagicMock, Mock, patch

from backend.services.email_sender import EmailSender


def test_email_sender_uses_mailtrap_smtp() -> None:
    smtp_instance = Mock()
    smtp_cls = MagicMock()
    smtp_cls.return_value.__enter__.return_value = smtp_instance

    with patch("backend.services.email_sender.smtplib.SMTP", smtp_cls):
        sender = EmailSender(
            host="sandbox.smtp.mailtrap.io",
            port=2525,
            username="user",
            password="pass",
            default_from="team@example.com",
        )
        result = sender.send_email("lead@example.com", "Hello", "Body")

    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("user", "pass")
    smtp_instance.send_message.assert_called_once()
    assert result["success"] is True
