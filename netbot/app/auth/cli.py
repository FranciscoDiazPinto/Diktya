"""Alta de usuarios desde la terminal.

Uso: python -m app.auth.cli correo contraseña [--role admin] [--name "Nombre"]

Si el correo ya existe, actualiza su contraseña, nombre y rol.
"""

import argparse
from getpass import getpass
from pydantic import ValidationError

from app.core.database import SessionLocal
from app.core.errors import ApplicationError
from app.bootstrap import initialize_database

from .roles import RoleName
from .schemas import UserCreate
from .service import provision_user


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea o actualiza un usuario de Netbot.")
    parser.add_argument("email")
    parser.add_argument("password", nargs="?", help="Si se omite, se solicita sin mostrarla.")
    parser.add_argument("--role", choices=[role.value for role in RoleName], default=RoleName.ADMIN.value)
    parser.add_argument("--name", default=None)
    args = parser.parse_args()
    password = args.password if args.password is not None else getpass("Contraseña: ")
    try:
        data = UserCreate(email=args.email, password=password, full_name=args.name, roles=[args.role])
    except ValidationError:
        parser.error("revisa el correo, el nombre y la contraseña (8 a 128 caracteres)")
    initialize_database()
    try:
        with SessionLocal() as db:
            user = provision_user(data, db)
            print(f"Usuario {user.email} configurado con rol {args.role}.")
    except ApplicationError as exc:
        parser.exit(2, exc.detail + "\n")


if __name__ == "__main__":
    main()
