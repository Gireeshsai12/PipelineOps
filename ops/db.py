import hashlib
import json
import os
import secrets
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
DATABASE = os.getenv("DATABASE_URL", "postgresql+psycopg://pipeline:pipeline-local@db:5432/pipeline")
engine = create_engine(DATABASE, pool_pre_ping=True, pool_size=5)


def query(connection, statement, **params):
    return connection.execute(text(statement), params)


def one(connection, statement, **params):
    return query(connection, statement, **params).mappings().first()


def rows(connection, statement, **params):
    return [dict(row) for row in query(connection, statement, **params).mappings()]


def log(event, **fields):
    print(json.dumps({"event": event, **fields}, default=str), flush=True)


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ":" + hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                                      n=16384, r=8, p=1).hex()


def migrate():
    with engine.begin() as connection:
        query(connection, "SELECT pg_advisory_xact_lock(284713)")
        query(connection, "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)")
        for path in sorted((ROOT / "migrations").glob("*.sql")):
            if not one(connection, "SELECT name FROM schema_migrations WHERE name=:name", name=path.name):
                for statement in path.read_text().split(";"):
                    if statement.strip():
                        query(connection, statement)
                query(connection, "INSERT INTO schema_migrations VALUES (:name)", name=path.name)
        for workspace in ("north", "south"):
            query(connection, "INSERT INTO workspaces VALUES (:id,:name) ON CONFLICT DO NOTHING",
                  id=workspace, name=workspace.title() + " Operations")
        for username, role, workspace in (
            ("operator", "operator", "north"), ("viewer", "viewer", "north"),
            ("south-operator", "operator", "south"),
        ):
            query(connection, "INSERT INTO users VALUES (:user,:hash) ON CONFLICT DO NOTHING",
                  user=username, hash=password_hash("pipeline-demo"))
            query(connection, "INSERT INTO memberships VALUES (:workspace,:user,:role) ON CONFLICT DO NOTHING",
                  workspace=workspace, user=username, role=role)
    log("migrations_ready")


if __name__ == "__main__":
    migrate()
