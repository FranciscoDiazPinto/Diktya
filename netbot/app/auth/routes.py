from __future__ import annotations


from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db

from .dependencies import get_current_user, require_permission
from .models import User
from . import service
from .schemas import LoginRequest, RefreshRequest, RoleCreate, RoleRead, TokenResponse, UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/auth", tags=["authentication"])
admin_router = APIRouter(prefix="/admin", tags=["administration"])


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    return service.login(data, db)


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    return service.refresh(data, db)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(data: RefreshRequest, db: Session = Depends(get_db)) -> None:
    return service.logout(data, db)


@router.get("/me", response_model=UserRead)
def current_user(user: User = Depends(get_current_user)) -> UserRead:
    return service.user_read(user)


@admin_router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db), actor: User = Depends(require_permission("users:read"))) -> list[UserRead]:
    return service.list_users(db, actor)


@admin_router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, db: Session = Depends(get_db), actor: User = Depends(require_permission("users:manage"))) -> UserRead:
    return service.create_user(data, db, actor)


@admin_router.patch("/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db), actor: User = Depends(require_permission("users:manage"))) -> UserRead:
    return service.update_user(user_id, data, db, actor)


@admin_router.get("/roles", response_model=list[RoleRead])
def list_roles(db: Session = Depends(get_db), actor: User = Depends(require_permission("roles:manage"))) -> list[RoleRead]:
    return service.list_roles(db, actor)


@admin_router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(data: RoleCreate, db: Session = Depends(get_db), actor: User = Depends(require_permission("roles:manage"))) -> RoleRead:
    return service.create_role(data, db, actor)
