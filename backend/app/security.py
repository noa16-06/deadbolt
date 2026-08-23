"""Password hashing and signed session cookies.

Do not hand-roll any of this: argon2id for the password, itsdangerous for the
cookie.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

COOKIE_NAME = "dashboard_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 14  # 14 days

_hasher = PasswordHasher()
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="session")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def password_matches(hash_value: str, password: str) -> bool:
    try:
        _hasher.verify(hash_value, password)
        return True
    except (VerifyMismatchError, VerificationError):
        return False


def create_session(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session(token: str) -> int | None:
    """Return the user id, or None if the cookie is invalid or expired."""
    try:
        data = _serializer.loads(token, max_age=COOKIE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid")
    return uid if isinstance(uid, int) else None
