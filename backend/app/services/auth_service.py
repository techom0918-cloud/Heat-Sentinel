"""User accounts: signup, login, and forgot-password (Phase 16).

PROTOTYPE PERSISTENCE LAYER. Uses Python's stdlib `sqlite3` against a local
file (`settings.AUTH_DB_PATH`), not the PostgreSQL `DATABASE_URL` reserved
in config.py -- this is a lightweight, dependency-free account store for
personalization logins, not a production identity system. Swapping to a
real database later only touches this file.

Passwords and security-question answers are never stored in plain text:
both are hashed with PBKDF2-HMAC-SHA256 (stdlib `hashlib`, no new
dependency) under a random per-value salt (stdlib `secrets`). Login and
forgot-password failures return the same generic message regardless of
whether the email exists, the password was wrong, or an answer was wrong
-- so a caller cannot use this API to discover which emails are registered.

THIS IS AUTHENTICATION ONLY. No health, demographic, or heat-risk data is
stored here. Personalized risk factors (age, acclimatization history,
health flags) are a separate, not-yet-built concern.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ValidationError

_PBKDF2_ALGO = "sha256"
_MIN_EMAIL_LENGTH = 5  # shortest plausible "a@b.c"
_GENERIC_LOGIN_ERROR = "Incorrect email or password."
_GENERIC_RECOVERY_ERROR = "Email or security answers did not match."


def _db_path() -> Path:
    path = Path(settings.AUTH_DB_PATH)
    if not path.is_absolute():
        # Same convention as health_data_service._resolve: relative to
        # backend/, i.e. two levels above this file (services -> app -> backend).
        path = Path(__file__).resolve().parents[2] / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS is idempotent, so this runs on every
    connection rather than needing a separate migration/init step."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS security_answers (
            user_id INTEGER NOT NULL,
            question_index INTEGER NOT NULL,
            answer_hash TEXT NOT NULL,
            answer_salt TEXT NOT NULL,
            PRIMARY KEY (user_id, question_index),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reset_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )


# --- hashing -----------------------------------------------------------


def _hash(value: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt_hex = salt_hex or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGO,
        value.encode("utf-8"),
        bytes.fromhex(salt_hex),
        settings.AUTH_PBKDF2_ITERATIONS,
    )
    return digest.hex(), salt_hex


def _verify(value: str, stored_hash: str, stored_salt: str) -> bool:
    computed, _ = _hash(value, stored_salt)
    return secrets.compare_digest(computed, stored_hash)


def _normalize_answer(answer: str) -> str:
    """Case/whitespace-insensitive so "Simba" and " simba " both match."""
    return answer.strip().lower()


# --- validation ----------------------------------------------------------


def _validate_email(email: str) -> str:
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    if not local or "." not in domain or len(email) < _MIN_EMAIL_LENGTH:
        raise ValidationError("Enter a valid email address.", details={"field": "email"})
    return email


def _validate_security_answers(security_answers: list[dict[str, Any]]) -> None:
    required = settings.AUTH_SECURITY_QUESTIONS_REQUIRED
    if len(security_answers) < required:
        raise ValidationError(
            f"At least {required} security questions must be answered.",
            details={"field": "security_answers", "required": required},
        )
    questions = settings.auth_security_questions_list
    seen: set[int] = set()
    for item in security_answers:
        idx = item["question_index"]
        if idx < 0 or idx >= len(questions):
            raise ValidationError(
                "Unknown security question.", details={"question_index": idx}
            )
        if idx in seen:
            raise ValidationError(
                "Each security question can only be answered once.",
                details={"question_index": idx},
            )
        seen.add(idx)
        if not item["answer"].strip():
            raise ValidationError(
                "Security answers cannot be empty.", details={"question_index": idx}
            )


def _validate_password(password: str) -> None:
    if len(password) < settings.AUTH_PASSWORD_MIN_LENGTH:
        raise ValidationError(
            f"Password must be at least {settings.AUTH_PASSWORD_MIN_LENGTH} characters.",
            details={"field": "password"},
        )


# --- signup / login --------------------------------------------------------


def signup(
    email: str, password: str, security_answers: list[dict[str, Any]]
) -> dict[str, Any]:
    email = _validate_email(email)
    _validate_password(password)
    _validate_security_answers(security_answers)

    password_hash, password_salt = _hash(password)
    now = time.time()
    with _connect() as conn:
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            raise ValidationError(
                "An account already exists for this email.",
                details={"field": "email"},
            )
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, password_salt, created_at) "
            "VALUES (?, ?, ?, ?)",
            (email, password_hash, password_salt, now),
        )
        user_id = cur.lastrowid
        for item in security_answers:
            answer_hash, answer_salt = _hash(_normalize_answer(item["answer"]))
            conn.execute(
                "INSERT INTO security_answers "
                "(user_id, question_index, answer_hash, answer_salt) VALUES (?, ?, ?, ?)",
                (user_id, item["question_index"], answer_hash, answer_salt),
            )
        conn.commit()
    return {"email": email, "created_at": now}


def login(email: str, password: str) -> dict[str, Any]:
    email = _validate_email(email)
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, password_hash, password_salt FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None or not _verify(password, row["password_hash"], row["password_salt"]):
            raise AuthenticationError(_GENERIC_LOGIN_ERROR)

        token = secrets.token_urlsafe(settings.AUTH_SESSION_TOKEN_BYTES)
        expires_at = time.time() + settings.AUTH_SESSION_EXPIRY_SECONDS
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, row["id"], expires_at),
        )
        conn.commit()
    return {"session_token": token, "expires_at": expires_at, "email": email}


def get_current_user(token: str) -> dict[str, Any]:
    if not token:
        raise AuthenticationError("Missing session token.")
    with _connect() as conn:
        row = conn.execute(
            "SELECT sessions.expires_at AS expires_at, users.email AS email, "
            "users.created_at AS created_at "
            "FROM sessions JOIN users ON users.id = sessions.user_id "
            "WHERE sessions.token = ?",
            (token,),
        ).fetchone()
        if row is None or row["expires_at"] < time.time():
            raise AuthenticationError("Session is invalid or has expired.")
        return {"email": row["email"], "created_at": row["created_at"]}


# --- forgot password ---------------------------------------------------


def verify_security_answers(
    email: str, security_answers: list[dict[str, Any]]
) -> dict[str, Any]:
    email = _validate_email(email)
    required = settings.AUTH_SECURITY_QUESTIONS_REQUIRED
    if len(security_answers) < required:
        raise ValidationError(
            f"At least {required} security questions must be answered.",
            details={"field": "security_answers", "required": required},
        )

    with _connect() as conn:
        user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if user is None:
            # Same message as a wrong answer -- never reveal whether the
            # email is registered.
            raise AuthenticationError(_GENERIC_RECOVERY_ERROR)

        rows = conn.execute(
            "SELECT question_index, answer_hash, answer_salt "
            "FROM security_answers WHERE user_id = ?",
            (user["id"],),
        ).fetchall()
        stored = {r["question_index"]: (r["answer_hash"], r["answer_salt"]) for r in rows}

        for item in security_answers:
            idx = item["question_index"]
            if idx not in stored:
                raise AuthenticationError(_GENERIC_RECOVERY_ERROR)
            answer_hash, answer_salt = stored[idx]
            if not _verify(_normalize_answer(item["answer"]), answer_hash, answer_salt):
                raise AuthenticationError(_GENERIC_RECOVERY_ERROR)

        token = secrets.token_urlsafe(settings.AUTH_SESSION_TOKEN_BYTES)
        expires_at = time.time() + settings.AUTH_RESET_TOKEN_EXPIRY_SECONDS
        conn.execute(
            "INSERT INTO reset_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user["id"], expires_at),
        )
        conn.commit()
    return {"reset_token": token, "expires_at": expires_at}


def reset_password(reset_token: str, new_password: str) -> dict[str, Any]:
    _validate_password(new_password)
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id, expires_at FROM reset_tokens WHERE token = ?",
            (reset_token,),
        ).fetchone()
        if row is None or row["expires_at"] < time.time():
            raise AuthenticationError("Reset link is invalid or has expired.")

        password_hash, password_salt = _hash(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
            (password_hash, password_salt, row["user_id"]),
        )
        conn.execute("DELETE FROM reset_tokens WHERE token = ?", (reset_token,))
        # A password reset invalidates every existing session so an old,
        # already-issued login token can't outlive the password it was
        # issued under.
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
        conn.commit()
    return {"status": "password_reset"}
