from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from backend.admin.db import get_connection
from backend.admin.repository import now_iso


HASH_PREFIX = "pbkdf2_sha256"
ITERATIONS = 120_000


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt.encode("utf-8"), ITERATIONS)
    return f"{HASH_PREFIX}${ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        prefix, iterations_text, salt, expected_hex = encoded.split("$", 3)
        if prefix != HASH_PREFIX:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt.encode("utf-8"), int(iterations_text))
        return hmac.compare_digest(digest.hex(), expected_hex)
    except Exception:
        return False


def add_admin_user(email: str, password: str) -> dict[str, Any]:
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        raise ValueError("Admin email must be a valid email address")
    if not password:
        raise ValueError("Password cannot be empty")
    timestamp = now_iso()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO admin_users (email, password_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                password_hash = excluded.password_hash,
                updated_at = excluded.updated_at
            """,
            (normalized, hash_password(password), timestamp, timestamp),
        )
        conn.commit()
        return {"email": normalized, "created_at": timestamp}
    finally:
        conn.close()


def list_admin_users() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT email, created_at, updated_at FROM admin_users ORDER BY email ASC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def remove_admin_user(email: str) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM admin_users WHERE email = ?", (normalize_email(email),))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def authenticate_admin(email: str, password: str) -> dict[str, Any] | None:
    normalized = normalize_email(email)
    conn = get_connection()
    try:
        row = conn.execute("SELECT email, password_hash, created_at, updated_at FROM admin_users WHERE email = ?", (normalized,)).fetchone()
        if not row:
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        return {"email": row["email"], "created_at": row["created_at"], "updated_at": row["updated_at"]}
    finally:
        conn.close()
