from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import psycopg

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS opspilot_schema_migrations (
    version text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""
_MIGRATION_LOCK_NAME = "opspilot:schema-migrations"


class MigrationDriftError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MigrationResult:
    applied: tuple[str, ...]
    already_applied: tuple[str, ...]


def apply_migrations(database_url: str, directory: Path) -> MigrationResult:
    migration_files = sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    if not migration_files:
        raise ValueError(f"no migrations found in {directory}")

    applied: list[str] = []
    already_applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(_CREATE_MIGRATIONS_TABLE)
        connection.execute(
            "SELECT pg_advisory_lock(hashtext(%s))",
            (_MIGRATION_LOCK_NAME,),
        )
        try:
            rows = connection.execute(
                "SELECT version, checksum FROM opspilot_schema_migrations"
            ).fetchall()
            known = {str(version): str(checksum) for version, checksum in rows}

            for migration_file in migration_files:
                version = migration_file.stem
                sql = migration_file.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode()).hexdigest()
                if version in known:
                    if known[version] != checksum:
                        raise MigrationDriftError(
                            f"applied migration {version} no longer matches its checksum"
                        )
                    already_applied.append(version)
                    continue

                with connection.transaction():
                    connection.execute(sql)
                    connection.execute(
                        """
                        INSERT INTO opspilot_schema_migrations (version, checksum)
                        VALUES (%s, %s)
                        """,
                        (version, checksum),
                    )
                applied.append(version)
        finally:
            connection.execute(
                "SELECT pg_advisory_unlock(hashtext(%s))",
                (_MIGRATION_LOCK_NAME,),
            )

    return MigrationResult(tuple(applied), tuple(already_applied))
