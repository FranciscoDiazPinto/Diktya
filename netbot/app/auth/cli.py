"""Alta de usuarios desde la terminal.

Uso: python -m app.auth.cli correo contraseña [--role admin] [--name "Nombre"]

Si el correo ya existe, actualiza su contraseña, nombre y rol.
"""

import argparse

from sqlalchemy import select

from app.core.database import SessionLocal
from app.main import initialize_database

from .models import Role, User
from .roles import RoleName
from .security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea o actualiza un usuario de Netbot.")
    parser.add_argument("email")
    parser.add_argument("password")
    parser.add_argument("--role", choices=[role.value for role in RoleName], default=RoleName.ADMIN.value)
    parser.add_argument("--name", default=None)
    args = parser.parse_args()
    if len(args.password) < 8:
        parser.error("la contraseña debe tener al menos 8 caracteres")

    initialize_database()  # crea tablas y roles si la base está vacía
    db = SessionLocal()
    try:
        role = db.scalar(select(Role).where(Role.name == args.role))
        email = args.email.lower()
        user = db.scalar(select(User).where(User.email == email))
        action = "actualizado" if user else "creado"
        if not user:
            user = User(email=email)
            db.add(user)
        user.hashed_password = hash_password(args.password)
        user.full_name = args.name or user.full_name
        user.is_active = True
        user.roles = [role]
        db.commit()
        print(f"Usuario {email} {action} con rol {args.role}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
