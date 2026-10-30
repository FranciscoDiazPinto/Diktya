from __future__ import annotations
from typing import Optional

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=160)
    roles: list[str] = Field(default_factory=lambda: ["visor"], min_length=1, max_length=20)

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, roles):
        if len(set(roles)) != len(roles):
            raise ValueError("No repitas roles.")
        return roles


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: Optional[str] = Field(default=None, max_length=160)
    is_active: Optional[bool] = None
    roles: Optional[list[str]] = Field(default=None, min_length=1, max_length=20)
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, roles):
        return UserCreate.unique_roles(roles) if roles is not None else roles


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: Optional[str]
    is_active: bool
    roles: list[str]
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime


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
