import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.core import config
from app.schemas.profile import ShopProfile
from app.services import profile_extractor


@pytest.fixture(autouse=True)
def gemini_mock(monkeypatch):
    """All tests are offline; no real key or Gemini call is used."""
    factory = MagicMock()
    client = factory.return_value.__enter__.return_value
    client.models.generate_content.return_value = SimpleNamespace(
        text=ShopProfile(shop_name=None, business_type=None).model_dump_json()
    )
    monkeypatch.setattr(profile_extractor.genai, "Client", factory)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-only-gemini-key")
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-3.8-flash")
    return factory


@pytest.fixture
def api_client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def fewshot_data(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "answers").mkdir(parents=True)
    (data_dir / "samples").mkdir()
    ids = [1, 7, 13, 19, 25]
    (data_dir / "split.json").write_text(json.dumps({"train": ids, "eval": [2, 3]}), encoding="utf-8")
    # Synthetic fixtures stay in temporary directories, never production data/.
    answers = [{"id": value, "profile": ShopProfile(shop_name=None, business_type=None).model_dump()} for value in reversed(ids)]
    texts = [{"id": value, "text": f"테스트 원문 {value}"} for value in ids]
    texts.append({"id": 2, "text": "EVAL_MUST_NEVER_APPEAR"})
    for path, rows in [
        (data_dir / "answers" / "fewshot_profiles.jsonl", answers),
        (data_dir / "samples" / "shop_texts.jsonl", texts),
    ]:
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    return data_dir
