import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.core import config
from app.schemas.concept import Concept, can_suggest
from app.services.concept_suggester import auto_concept
from app.schemas.design import SavedDesign
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
        connection.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(shops)")}
        if "concept_json" not in columns:
            connection.execute("ALTER TABLE shops ADD COLUMN concept_json TEXT")
        if "menu_origins_json" not in columns:
            connection.execute("ALTER TABLE shops ADD COLUMN menu_origins_json TEXT")
        if "menu_names_en_json" not in columns:
            connection.execute("ALTER TABLE shops ADD COLUMN menu_names_en_json TEXT")
        if "design_json" not in columns:
            connection.execute("ALTER TABLE shops ADD COLUMN design_json TEXT")


def save_shop(profile: ShopProfile, source_text: str, prompt_version: str,
              shop_id: int | None = None, *, concept: Concept | None = None,
              design: SavedDesign | None = None, menu_origins: dict[str, str] | None = None, db_path: Path | None = None) -> int:
    profile = normalize_saved_profile(profile)
    if concept is not None:
        concept = Concept.model_validate(concept)
    saved = get_shop(shop_id, db_path=db_path) if shop_id is not None else None
    automatic = concept is None and can_suggest(profile)
    if automatic:
        previous = Concept.model_validate(saved["concept"]) if saved and saved["concept"] else None
        if previous is not None and previous.source == "자동" and saved["source_text"] == source_text:
            concept = previous
        else:
            # Keep the network request outside the SQLite write transaction.
            concept = auto_concept(profile, source_text)
    concept_json = concept.model_dump_json() if concept is not None else None
    design_json = SavedDesign.model_validate(design).model_dump_json() if design is not None else None
    menu_names = {item.name for item in profile.menus or []}
    origins_json = None if menu_origins is None else json.dumps({
        name: value.strip() for name, value in menu_origins.items() if name in menu_names and value.strip()
    }, ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    values = (profile.shop_name, profile.business_type,
              json.dumps(profile.model_dump(), ensure_ascii=False), source_text, prompt_version)
    with _connection(db_path) as connection:
        if shop_id is None:
            cursor = connection.execute(
                "INSERT INTO shops (shop_name,business_type,profile_json,source_text,prompt_version,created_at,updated_at,concept_json,design_json,menu_origins_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (*values, now, now, concept_json, design_json, origins_json),
            )
            return cursor.lastrowid
        if automatic:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT source_text,concept_json FROM shops WHERE id=?", (shop_id,)).fetchone()
            if current is not None and current["source_text"] == source_text and current["concept_json"]:
                current_concept = Concept.model_validate_json(current["concept_json"])
                if current_concept.source == "자동":
                    concept_json = current["concept_json"]
        cursor = connection.execute(
            "UPDATE shops SET shop_name=?,business_type=?,profile_json=?,source_text=?,prompt_version=?,updated_at=?,concept_json=?,design_json=COALESCE(?,design_json),menu_origins_json=COALESCE(?,menu_origins_json) WHERE id=?",
            (*values, now, concept_json, design_json, origins_json, shop_id),
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
        "design": json.loads(row["design_json"]) if row["design_json"] else None,
        "menu_origins": json.loads(row["menu_origins_json"]) if row["menu_origins_json"] else {},
        "menu_names_en": json.loads(row["menu_names_en_json"]) if row["menu_names_en_json"] else {},
        "source_text": row["source_text"], "prompt_version": row["prompt_version"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def save_menu_names_en(shop_id, profile_snapshot, translations):
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT profile_json,menu_names_en_json FROM shops WHERE id=?", (shop_id,)).fetchone()
        if row is not None and json.loads(row["profile_json"]) == profile_snapshot:
            translations = {**json.loads(row["menu_names_en_json"] or "{}"), **translations}
            connection.execute("UPDATE shops SET menu_names_en_json=? WHERE id=?",
                               (json.dumps(translations, ensure_ascii=False), shop_id))
