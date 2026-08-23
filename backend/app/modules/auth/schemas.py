"""Input and output models of the auth module (validation at the boundary)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    # A TOTP code or a recovery code. Optional, because most accounts have no
    # second factor — the backend decides whether it is required, not the form.
    code: str | None = Field(default=None, max_length=64)


class TotpConfirmInput(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class TotpSetupOut(BaseModel):
    """Shown once, while enrolling."""

    secret: str
    uri: str


class TotpConfirmOut(BaseModel):
    """The recovery codes. This is the only time they exist in plain text."""

    recovery_codes: list[str] = Field(serialization_alias="recoveryCodes")


class UserOut(BaseModel):
    id: int
    username: str
    totp_enabled: bool = Field(default=False, serialization_alias="totpEnabled")
    # Not a property of the user. It rides along here because /auth/me is the
    # first thing the app fetches on boot, so the client learns it is running
    # without a login without a second request.
    auth_disabled: bool = Field(default=False, serialization_alias="authDisabled")

    model_config = {"from_attributes": True}
