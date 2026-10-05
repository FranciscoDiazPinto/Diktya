from __future__ import annotations
from typing import Optional

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: Optional[str] = None
    roles: list[str] = Field(default_factory=lambda: ["visor"])


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    roles: Optional[list[str]] = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: Optional[str]
    is_active: bool
    roles: list[str]
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: Optional[str] = None


class RoleRead(RoleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
