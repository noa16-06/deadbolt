"""Input and output models of the auth module (validation at the boundary)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    username: str

    model_config = {"from_attributes": True}
