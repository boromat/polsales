"""Tworzy/aktualizuje konto właściciela (system 1-użytkownikowy).

Uruchomienie interaktywne:      python -m app.scripts.create_user
Uruchomienie z env (Docker/CI): POLSALES_USERNAME=owner POLSALES_PASSWORD=... python -m app.scripts.create_user
"""

from __future__ import annotations

import getpass
import os
import sys

from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models.ops import Session as SessionModel
from app.db.models.ops import User
from app.security import hash_password


def main() -> None:
    username = os.environ.get("POLSALES_USERNAME")
    password = os.environ.get("POLSALES_PASSWORD")
    # Adres Google, którym wchodzi się przez Cloudflare Access. Opcjonalny - bez niego
    # konto działa tak jak dotąd, na login i hasło.
    email = (os.environ.get("POLSALES_EMAIL") or "").strip().lower() or None

    if not username:
        username = input("Login: ").strip()
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass("Hasło: ")
        else:
            print("Brak POLSALES_PASSWORD w środowisku (i brak terminala).", file=sys.stderr)
            sys.exit(1)

    if not username or not password:
        print("Login i hasło są wymagane.", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(username=username, password_hash=hash_password(password), email=email)
            db.add(user)
            print(f"Utworzono użytkownika '{username}'.")
        else:
            user.password_hash = hash_password(password)
            if email:
                user.email = email
            # Zmiana hasła unieważnia wszystkie sesje - skradzione cookie nie przeżyje resetu.
            db.execute(delete(SessionModel).where(SessionModel.user_id == user.id))
            print(f"Zaktualizowano hasło użytkownika '{username}' i wylogowano wszystkie sesje.")
        if email:
            print(f"Adres do logowania przez Google: {email}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
