"""The admin account and its login sessions.

The account is made once from ADMIN_USERNAME and ADMIN_PASSWORD; after that it is
changed in Settings → Account (or with `python -m app.reset_password`).
"""

import base64
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass

MIN_PASSWORD = 8
SESSION_DAYS = 30
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


@dataclass(frozen=True)
class User:
    id: int
    username: str


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    n, r, p = _SCRYPT.values()
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        found = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32, n=int(n), r=int(r), p=int(p))
    except ValueError:
        return False
    return hmac.compare_digest(found, base64.b64decode(digest))


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"The password needs at least {MIN_PASSWORD} characters."
    return None


def get_admin(conn: sqlite3.Connection) -> User | None:
    row = conn.execute("SELECT id, username FROM users ORDER BY id LIMIT 1").fetchone()
    return User(row["id"], row["username"]) if row else None


def save_admin(conn: sqlite3.Connection, username: str, password: str | None = None) -> User:
    """Make the admin account, or change its username and (when given) password."""
    admin = get_admin(conn)
    if admin is None:
        cursor = conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                              (username, hash_password(password or "")))
        return User(cursor.lastrowid, username)
    conn.execute("UPDATE users SET username = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (username, admin.id))
    if password:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), admin.id))
    return User(admin.id, username)


def check_login(conn: sqlite3.Connection, username: str, password: str) -> User | None:
    row = conn.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        verify_password(password, hash_password("timing"))  # same time whether the user exists or not
        return None
    return User(row["id"], row["username"]) if verify_password(password, row["password_hash"]) else None


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(conn: sqlite3.Connection, user: User) -> str:
    """A new session; returns the cookie value. Only its hash is stored."""
    now = int(time.time())
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                 (_digest(token), user.id, now + SESSION_DAYS * 86400))
    return token


def session_user(conn: sqlite3.Connection, token: str | None) -> User | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT users.id, users.username FROM sessions JOIN users ON users.id = sessions.user_id"
        " WHERE token_hash = ? AND expires_at > ?", (_digest(token), int(time.time()))
    ).fetchone()
    return User(row["id"], row["username"]) if row else None


def end_sessions(conn: sqlite3.Connection, token: str | None = None, keep: str | None = None) -> None:
    """End one session, or every session but `keep` (after a password change)."""
    if token is not None:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))
    else:
        conn.execute("DELETE FROM sessions WHERE token_hash != ?", (_digest(keep or ""),))


class Throttle:
    """After a few wrong passwords from one address, refuse its logins for a while."""

    def __init__(self, limit: int = 5, window: int = 900):
        self.limit, self.window = limit, window
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def wait(self, address: str) -> int:
        """Seconds to wait before trying again, 0 when a login may be tried."""
        now = time.time()
        with self._lock:
            recent = [t for t in self._failures.get(address, []) if now - t < self.window]
            self._failures[address] = recent
            return int(self.window - (now - recent[0])) + 1 if len(recent) >= self.limit else 0

    def failed(self, address: str) -> None:
        with self._lock:
            self._failures.setdefault(address, []).append(time.time())

    def succeeded(self, address: str) -> None:
        with self._lock:
            self._failures.pop(address, None)
