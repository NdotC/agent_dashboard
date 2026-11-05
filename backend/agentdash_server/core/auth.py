"""Einfache Anmeldung per Passwort (aus der Umgebung) und signiertem Session-Cookie."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path

COOKIE_NAME = "agentdash_session"


class Auth:
    def __init__(self, password: str | None, secret_key: str | None, data_dir: Path, session_hours: int) -> None:
        self.password = password or None
        self.session_seconds = session_hours * 3600
        self.secret = (secret_key or self._load_or_create_secret(data_dir)).encode()

    @staticmethod
    def _load_or_create_secret(data_dir: Path) -> str:
        path = data_dir / "secret.key"
        if path.exists():
            return path.read_text().strip()
        data_dir.mkdir(parents=True, exist_ok=True)
        value = secrets.token_hex(32)
        path.write_text(value)
        path.chmod(0o600)
        return value

    @property
    def enabled(self) -> bool:
        return self.password is not None

    def check_password(self, password: str) -> bool:
        return self.password is not None and hmac.compare_digest(password.encode(), self.password.encode())

    def _sign(self, payload: str) -> str:
        return hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        expires = int(time.time()) + self.session_seconds
        payload = f"{expires}.{secrets.token_hex(8)}"
        return f"{payload}.{self._sign(payload)}"

    def verify(self, token: str | None) -> bool:
        if not self.enabled:
            return True
        if not token or token.count(".") != 2:
            return False
        expires, nonce, sig = token.split(".")
        payload = f"{expires}.{nonce}"
        if not hmac.compare_digest(sig, self._sign(payload)):
            return False
        try:
            return int(expires) > time.time()
        except ValueError:
            return False
