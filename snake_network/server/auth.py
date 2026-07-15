import base64
import hashlib
import json
import re
import secrets
import threading
from pathlib import Path
from typing import Dict

from snake_network.shared.constants import PASSWORD_MIN, USERNAME_MAX, USERNAME_MIN


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


class UserStore:
    """File-backed user database with salted password hashes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._save({})

    def register(self, username: str, password: str) -> None:
        self._validate(username, password)
        with self._lock:
            users = self._load()
            key = username.lower()
            if key in users:
                raise ValueError("שם המשתמש כבר קיים")
            salt = secrets.token_bytes(16)
            users[key] = {
                "username": username,
                "salt": base64.b64encode(salt).decode("ascii"),
                "password_hash": self._hash_password(password, salt),
            }
            self._save(users)

    def login(self, username: str, password: str) -> str:
        with self._lock:
            users = self._load()
            record = users.get(username.lower())
            if record is None:
                raise ValueError("שם משתמש או ססמה שגויים")
            salt = base64.b64decode(record["salt"])
            attempted_hash = self._hash_password(password, salt)
            if not secrets.compare_digest(attempted_hash, record["password_hash"]):
                raise ValueError("שם משתמש או ססמה שגויים")
            return record["username"]

    def _validate(self, username: str, password: str) -> None:
        if not USERNAME_MIN <= len(username) <= USERNAME_MAX:
            raise ValueError(f"שם המשתמש חייב להיות באורך {USERNAME_MIN}-{USERNAME_MAX}")
        if not USERNAME_RE.match(username):
            raise ValueError("שם המשתמש יכול להכיל אותיות באנגלית, ספרות וקו תחתון בלבד")
        if len(password) < PASSWORD_MIN:
            raise ValueError(f"הססמה חייבת להכיל לפחות {PASSWORD_MIN} תווים")

    def _hash_password(self, password: str, salt: bytes) -> str:
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return base64.b64encode(digest).decode("ascii")

    def _load(self) -> Dict[str, Dict[str, str]]:
        with self._path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save(self, users: Dict[str, Dict[str, str]]) -> None:
        with self._path.open("w", encoding="utf-8") as file:
            json.dump(users, file, indent=2, ensure_ascii=False)
