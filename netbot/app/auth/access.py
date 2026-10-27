"""Autorización de aplicación reutilizable desde HTTP, chat y futuros trabajos."""
from sqlalchemy.orm import Session
from app.core.errors import Unauthenticated, AccessDenied
from .models import User
from .permissions import Permission
from .roles import effective_permissions


def require_user_permission(db: Session, user: User, permission: Permission) -> None:
    db.expire_all()
    if not user.is_active:
        raise Unauthenticated("Usuario inactivo.")
    if permission not in effective_permissions(user):
        raise AccessDenied("Permiso insuficiente.")
