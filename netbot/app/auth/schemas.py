from __future__ import annotations
from typing import Optional

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


COMMON_PASSWORDS = {"password1234", "contrasena123", "administrador", "qwertyuiopas", "123456789012", "netbot123456"}


def strong_password(value: str) -> str:
    """Longitud como control principal; rechaza solo lo trivial, sin reglas de composición."""
    if len(value) < 12 or len(set(value)) < 5 or value.lower() in COMMON_PASSWORDS:
        raise ValueError("Usa al menos 12 caracteres, sin repeticiones ni claves comunes.")
    return value


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=160)
    roles: list[str] = Field(default_factory=lambda: ["visor"], min_length=1, max_length=20)

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, roles):
        if len(set(roles)) != len(roles):
            raise ValueError("No repitas roles.")
        return roles

    _password = field_validator("password")(strong_password)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: Optional[str] = Field(default=None, max_length=160)
    is_active: Optional[bool] = None
    roles: Optional[list[str]] = Field(default=None, min_length=1, max_length=20)
    password: Optional[str] = Field(default=None, min_length=12, max_length=128)

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, roles):
        return UserCreate.unique_roles(roles) if roles is not None else roles

    @field_validator("password")
    @classmethod
    def password_strength(cls, value):
        return strong_password(value) if value is not None else value


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: Optional[str]
    is_active: bool
    roles: list[str]
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    _password = field_validator("new_password")(strong_password)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str = Field(min_length=1, max_length=256)
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=1, max_length=256)


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, max_length=255)


class RoleRead(RoleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class AuthAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: Optional[int]
    target_id: Optional[int]
    action: str
    outcome: str
    source: str
    details: dict
    created_at: datetime
