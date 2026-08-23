"""Password hashing and signed session cookies.

Do not hand-roll any of this: argon2id for the password, itsdangerous for the
cookie.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

COOKIE_NAME = "dashboard_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 14  # 14 days

# One step either side of the current 30 s window, so a clock that is a few
# seconds off does not lock anyone out. Two steps would widen the guessing
# window for no real gain.
TOTP_TOLERANCE = 1

RECOVERY_CODE_COUNT = 10

_hasher = PasswordHasher()
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="session")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def password_matches(hash_value: str, password: str) -> bool:
    try:
        _hasher.verify(hash_value, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHash):
        # InvalidHash: the stored value is not an argon2 hash at all. A damaged
        # row is a failed login, not a 500 on the login endpoint.
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


# --------------------------------------------------------------------- TOTP
def _fernet() -> Fernet:
    """Key for the TOTP secret, derived from SECRET_KEY.

    What this protects against: a leaked copy of `data/dashboard.db` — a backup
    that travelled without the `.env`. What it does NOT protect against: anyone
    who can read both files on the host. That is the honest scope; it is still
    worth it, because backups are exactly the thing that ends up somewhere else.

    Consequence: rotating SECRET_KEY makes existing TOTP secrets unreadable and
    every user has to enrol again. Rotating it already invalidates all sessions,
    so it was never a quiet operation.
    """
    key = hashlib.sha256(f"totp:{settings.secret_key}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_totp_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_totp_secret(stored: str) -> str | None:
    """None if the value cannot be read — a rotated SECRET_KEY, for instance."""
    try:
        return _fernet().decrypt(stored.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, username: str) -> str:
    """otpauth:// URI for the authenticator app."""
    return pyotp.TOTP(secret).provisioning_uri(
        name=username, issuer_name="Homelab Dashboard"
    )


def totp_matches(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=TOTP_TOLERANCE)


# ---------------------------------------------------------- recovery codes
def new_recovery_codes() -> list[str]:
    """Readable one-time codes, shown once and then only stored hashed."""
    return [
        f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}"
        for _ in range(RECOVERY_CODE_COUNT)
    ]


def hash_recovery_code(code: str) -> str:
    """Same hashing as for passwords — a recovery code IS a password."""
    return hash_password(normalise_recovery_code(code))


def recovery_code_matches(hash_value: str, code: str) -> bool:
    return password_matches(hash_value, normalise_recovery_code(code))


def normalise_recovery_code(code: str) -> str:
    """Nobody should fail because of capitals, spaces or missing dashes."""
    return code.strip().lower().replace(" ", "").replace("-", "")
