import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.core import config
from app.schemas.concept import Concept
from app.schemas.profile import ShopProfile
from app.schemas.profile_save import normalize_saved_profile


@contextmanager
def _connection(db_path: Path | None = None):
    path = Path(db_path if db_path is not None else config.SHOP_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db(db_path: Path | None = None) -> None:
    with _connection(db_path) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_name TEXT NOT NULL,
            business_type TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            source_text TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(shops)")}
        if "concept_json" not in columns:
            connection.execute("ALTER TABLE shops ADD COLUMN concept_json TEXT")


def save_shop(profile: ShopProfile, source_text: str, prompt_version: str,
              shop_id: int | None = None, *, concept: Concept | None = None, db_path: Path | None = None) -> int:
    profile = normalize_saved_profile(profile)
    if concept is not None:
        concept = Concept.model_validate(concept)
    concept_json = concept.model_dump_json() if concept is not None else None
    now = datetime.now(timezone.utc).isoformat()
    values = (profile.shop_name, profile.business_type,
              json.dumps(profile.model_dump(), ensure_ascii=False), source_text, prompt_version)
    with _connection(db_path) as connection:
        if shop_id is None:
            cursor = connection.execute(
                "INSERT INTO shops (shop_name,business_type,profile_json,source_text,prompt_version,created_at,updated_at,concept_json) VALUES (?,?,?,?,?,?,?,?)",
                (*values, now, now, concept_json),
            )
            return cursor.lastrowid
        cursor = connection.execute(
            "UPDATE shops SET shop_name=?,business_type=?,profile_json=?,source_text=?,prompt_version=?,updated_at=?,concept_json=? WHERE id=?",
            (*values, now, concept_json, shop_id),
        )
        if cursor.rowcount != 1:
            raise LookupError("저장된 가게를 찾을 수 없습니다")
        return shop_id


def list_shops(*, db_path: Path | None = None) -> list[dict]:
    with _connection(db_path) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT id,shop_name,business_type,updated_at FROM shops ORDER BY updated_at DESC,id DESC"
        ).fetchall()]


def get_shop(shop_id: int, *, db_path: Path | None = None) -> dict:
    with _connection(db_path) as connection:
        row = connection.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    if row is None:
        raise LookupError("저장된 가게를 찾을 수 없습니다")
    return {
        "shop_id": row["id"], "profile": json.loads(row["profile_json"]),
        "concept": json.loads(row["concept_json"]) if row["concept_json"] else None,
        "source_text": row["source_text"], "prompt_version": row["prompt_version"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }
