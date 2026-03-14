import smtplib
from email.message import EmailMessage
from typing import Any

from backend.app.config import get_settings
from backend.services import ServiceConfigurationError


class EmailSender:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        default_from: str | None = None,
    ):
        settings = get_settings()
        self.host = host or settings.MAILTRAP_HOST
        self.port = port or settings.MAILTRAP_PORT
        self.username = username or settings.MAILTRAP_USERNAME
        self.password = password or settings.MAILTRAP_PASSWORD
        self.default_from = default_from or settings.EMAIL_FROM

    def send_email(self, to: str, subject: str, body: str) -> dict[str, Any]:
        if not all([self.host, self.port, self.username, self.password]):
            raise ServiceConfigurationError("Mailtrap SMTP credentials are not fully configured")

        message = EmailMessage()
        message["From"] = self.default_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self.host, self.port, timeout=20) as server:
            server.starttls()
            server.login(self.username, self.password)
            server.send_message(message)

        return {
            "success": True,
            "status_code": 250,
            "provider_message_id": message.get("Message-ID"),
        }
