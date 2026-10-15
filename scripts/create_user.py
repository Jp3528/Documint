"""Local provisioning with hidden password input; no public registration endpoint."""

import argparse
from getpass import getpass

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.config import get_settings
from packages.database import make_engine
from packages.identity.models import User, UserRole
from packages.identity.policies import RoleName
from packages.identity.security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=[role.value for role in RoleName], default="EMPLOYEE")
    args = parser.parse_args()
    email = str(TypeAdapter(EmailStr).validate_python(args.email.strip().casefold()))
    name = args.name.strip()
    if not 1 <= len(name) <= 120:
        raise SystemExit("El nombre debe tener entre 1 y 120 caracteres.")
    password = getpass("Contraseña (12-128 caracteres): ")
    if password != getpass("Repite la contraseña: "):
        raise SystemExit("Las contraseñas no coinciden.")
    encoded = hash_password(password)
    engine = make_engine(get_settings())
    try:
        with Session(engine) as db:
            if db.scalar(select(User.id).where(User.email == email)) is not None:
                raise SystemExit("El usuario ya existe; no se modificó su contraseña.")
            user = User(email=email, display_name=name, password_hash=encoded)
            db.add(user)
            db.flush()
            db.add(UserRole(user_id=user.id, role_name=args.role))
            db.commit()
        print("PASS: local user created")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
