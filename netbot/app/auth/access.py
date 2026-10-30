"""Autorización de aplicación reutilizable desde HTTP, chat y futuros trabajos."""
from sqlalchemy.orm import Session
from app.core.errors import Unauthenticated, AccessDenied
from .models import User
from .permissions import Permission
from .audit import bind_request, queue_denial
from .roles import effective_permissions


def require_user_permission(db: Session, user: User, permission: Permission) -> None:
    bind_request(db, user.id)
    db.expire_all()
    if not user.is_active:
        queue_denial(user.id, permission, reason="inactive")
        raise Unauthenticated("Usuario inactivo.")
    if permission not in effective_permissions(user):
        queue_denial(user.id, permission)
        raise AccessDenied("Permiso insuficiente.")
