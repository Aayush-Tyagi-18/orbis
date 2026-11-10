"""Postgres (Neon) persistence. Rows are small JSON blobs; every row belongs to one user."""
from __future__ import annotations

import os
from typing import Type, TypeVar

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

load_dotenv()

T = TypeVar("T", bound=BaseModel)
TABLES = ("sources", "programs", "requirements", "deadlines", "documents")


def _check(table: str) -> str:
    """Table names are interpolated into SQL, so only allow the fixed list."""
    if table not in TABLES:
        raise ValueError(f"Unknown table: {table!r}")
    return table


class Store:
    def __init__(self, dsn: str | None = None):
        dsn = dsn or os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL is not set. Put the pooled Neon connection string in .env."
            )
        # Neon scales to zero and drops idle connections, so check each connection
        # before handing it out and allow a generous first-connect timeout.
        self.pool = ConnectionPool(
            dsn, min_size=1, max_size=5, open=False, max_idle=300,
            check=ConnectionPool.check_connection,
        )
        self.pool.open(wait=True, timeout=30)
        with self.pool.connection() as c:
            for t in TABLES:
                c.execute(
                    f"""CREATE TABLE IF NOT EXISTS {t} (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        program_id TEXT,
                        body JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )"""
                )
                c.execute(f"CREATE INDEX IF NOT EXISTS {t}_user_idx ON {t} (user_id, program_id)")

    def close(self) -> None:
        self.pool.close()

    def put(self, user_id: str, table: str, obj: BaseModel, program_id: str | None = None) -> None:
        t = _check(table)
        with self.pool.connection() as c:
            # The WHERE clause stops one user's write from ever replacing another user's row.
            c.execute(
                f"""INSERT INTO {t} (id, user_id, program_id, body) VALUES (%s, %s, %s, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE
                    SET program_id = EXCLUDED.program_id, body = EXCLUDED.body
                    WHERE {t}.user_id = EXCLUDED.user_id""",
                (obj.id, user_id, program_id, obj.model_dump_json()),  # type: ignore[attr-defined]
            )

    def get(self, user_id: str, table: str, id_: str, model: Type[T]) -> T | None:
        t = _check(table)
        with self.pool.connection() as c:
            row = c.execute(
                f"SELECT body::text FROM {t} WHERE id = %s AND user_id = %s", (id_, user_id)
            ).fetchone()
        return model.model_validate_json(row[0]) if row else None

    def list(self, user_id: str, table: str, model: Type[T], program_id: str | None = None) -> list[T]:
        t = _check(table)
        with self.pool.connection() as c:
            if program_id is None:
                rows = c.execute(
                    f"SELECT body::text FROM {t} WHERE user_id = %s ORDER BY created_at, id", (user_id,)
                ).fetchall()
            else:
                rows = c.execute(
                    f"SELECT body::text FROM {t} WHERE user_id = %s AND program_id = %s ORDER BY created_at, id",
                    (user_id, program_id),
                ).fetchall()
        return [model.model_validate_json(r[0]) for r in rows]

    def delete(self, user_id: str, table: str, id_: str) -> None:
        t = _check(table)
        with self.pool.connection() as c:
            c.execute(f"DELETE FROM {t} WHERE id = %s AND user_id = %s", (id_, user_id))

    def delete_program(self, user_id: str, program_id: str) -> None:
        """Delete a program with its requirements, deadlines and the source text it was read from."""
        with self.pool.connection() as c:  # one transaction
            c.execute(
                """DELETE FROM sources WHERE user_id = %s AND id IN (
                       SELECT jsonb_array_elements_text(body->'source_ids')
                       FROM programs WHERE id = %s AND user_id = %s)""",
                (user_id, program_id, user_id),
            )
            for t in ("requirements", "deadlines"):
                c.execute(f"DELETE FROM {t} WHERE program_id = %s AND user_id = %s", (program_id, user_id))
            c.execute("DELETE FROM programs WHERE id = %s AND user_id = %s", (program_id, user_id))

    def wipe(self, user_id: str) -> None:
        """Delete everything this user owns. Backs the 'delete my data' button."""
        with self.pool.connection() as c:
            for t in TABLES:
                c.execute(f"DELETE FROM {t} WHERE user_id = %s", (user_id,))
