"""Хранилище телеметрии на SQLite."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    request_id     TEXT PRIMARY KEY,
    timestamp      TEXT NOT NULL,
    model          TEXT NOT NULL,
    prompt         TEXT NOT NULL,
    response       TEXT NOT NULL,
    latency_ms     REAL NOT NULL,
    input_tokens   INTEGER NOT NULL,
    output_tokens  INTEGER NOT NULL,
    endpoint       TEXT NOT NULL,
    language       TEXT NOT NULL,
    topic          TEXT NOT NULL,
    cost_usd       REAL NOT NULL,
    prompt_tokens_est INTEGER NOT NULL DEFAULT 0,
    stages_json    TEXT NOT NULL DEFAULT '{}',
    scenario       TEXT NOT NULL DEFAULT 'manual',
    error          TEXT
);
CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry(timestamp);
CREATE INDEX IF NOT EXISTS idx_telemetry_scenario ON telemetry(scenario);
"""

COLUMNS = [
    "request_id", "timestamp", "model", "prompt", "response", "latency_ms",
    "input_tokens", "output_tokens", "endpoint", "language", "topic",
    "cost_usd", "prompt_tokens_est", "stages_json", "scenario", "error",
]


@contextmanager
def connect(db_path: Path = DB_PATH):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def save(record: dict[str, Any], db_path: Path = DB_PATH) -> None:
    row = dict(record)
    row["stages_json"] = json.dumps(row.pop("stages", {}), ensure_ascii=False)
    row.setdefault("scenario", "manual")
    row.setdefault("error", None)
    row.setdefault("prompt_tokens_est", 0)
    values = [row.get(col) for col in COLUMNS]
    placeholders = ", ".join("?" * len(COLUMNS))
    with connect(db_path) as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO telemetry ({', '.join(COLUMNS)}) VALUES ({placeholders})",
            values,
        )


def fetch(limit: int | None = None, scenario: str | None = None,
          db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    query = "SELECT * FROM telemetry"
    params: list[Any] = []
    if scenario:
        query += " WHERE scenario = ?"
        params.append(scenario)
    query += " ORDER BY timestamp DESC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    with connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["stages"] = json.loads(item.pop("stages_json") or "{}")
        result.append(item)
    return result


def count(db_path: Path = DB_PATH) -> int:
    with connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM telemetry").fetchone()["n"]


def export_csv(path: Path, rows: Iterable[dict[str, Any]] | None = None,
               db_path: Path = DB_PATH) -> Path:
    import csv

    rows = list(rows) if rows is not None else fetch(db_path=db_path)
    fields = [c for c in COLUMNS if c != "stages_json"] + ["stages_json"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            item = dict(row)
            item["stages_json"] = json.dumps(item.get("stages", {}), ensure_ascii=False)
            writer.writerow(item)
    return path
