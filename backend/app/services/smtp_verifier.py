import smtplib
import socket
import threading
import time
from collections import deque
from typing import Any

import dns.resolver

from backend.app.config import get_settings


class SMTPVerifierService:
    def __init__(self):
        self.settings = get_settings()
        self._history: deque[float] = deque()
        self._lock = threading.Lock()

    def verify(self, email: str, from_address: str) -> dict[str, Any]:
        self._throttle()
        domain = email.split("@")[-1].lower()
        mx_records = dns.resolver.resolve(domain, "MX")
        mx_host = str(sorted(mx_records, key=lambda record: record.preference)[0].exchange).rstrip(".")

        server = smtplib.SMTP(timeout=20)
        try:
            server.connect(mx_host, 25)
            server.helo(socket.getfqdn())
            server.mail(from_address)
            code, message = server.rcpt(email)
            accepted = code in {250, 251}
            rejected = code in {550, 553}
            return {
                "email": email,
                "is_valid": accepted and not rejected,
                "code": code,
                "message": message.decode() if isinstance(message, bytes) else str(message),
            }
        finally:
            try:
                server.quit()
            except Exception:
                pass

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._history and now - self._history[0] >= 60:
                self._history.popleft()
            if len(self._history) >= self.settings.SMTP_VERIFY_PER_MINUTE:
                sleep_for = 60 - (now - self._history[0])
                if sleep_for > 0 and not self.settings.TASKS_ALWAYS_EAGER:
                    time.sleep(sleep_for)
            self._history.append(time.monotonic())
