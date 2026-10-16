"""Generate local secret files without printing credentials or contacting Tuya."""
import argparse
import getpass
import os
import secrets
from pathlib import Path
from argon2 import PasswordHasher


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="/secrets")
    args = parser.parse_args()
    folder = Path(args.dir)
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    names = ["postgres_password", "database_url", "admin_password_hash", "tuya_access_id", "tuya_access_secret", "restic_password"]
    if any((folder / name).exists() for name in names):
        raise SystemExit("Segredos já existem. Rotacione-os manualmente, sem sobrescrever o banco.")
    password = getpass.getpass("Senha administrativa (mínimo 14 caracteres): ")
    if len(password) < 14 or password != getpass.getpass("Confirme a senha: "):
        raise SystemExit("Senha curta ou confirmação diferente")
    access_id = getpass.getpass("Tuya Access ID: ").strip()
    access_secret = getpass.getpass("Tuya Access Secret: ").strip()
    if not access_id or len(access_secret) < 24:
        raise SystemExit("Credenciais Tuya obrigatórias")
    db_password = secrets.token_hex(32)
    values = [db_password, f"postgresql+psycopg://tuya:{db_password}@db:5432/tuya",
              PasswordHasher().hash(password), access_id, access_secret, secrets.token_urlsafe(48)]
    for name, value in zip(names, values):
        file = folder / name
        file.write_text(value)
        os.chmod(file, 0o600)
    # Compose file secrets preserve host permissions; container app UID is 10001.
    if hasattr(os, "chown"):
        for name in names:
            owner = 999 if name == "postgres_password" else 10001
            os.chown(folder / name, owner, owner)
    print("Segredos gerados. Guarde uma cópia protegida da senha de backup fora deste servidor.")


if __name__ == "__main__":
    main()
