"""Translate saved menu names in a single structured request."""
import json

from app.schemas.profile import ProfileModel
from app.services.llm_client import generate_json


class MenuNames(ProfileModel):
    names: list[str | None]


def translate(names):
    raw = generate_json(
        "메뉴명을 같은 순서로 짧은 영어 메뉴명으로 번역하세요. 이름만 번역하고 재료나 특징을 추가하지 마세요.",
        json.dumps(names, ensure_ascii=False), MenuNames.model_json_schema(), None, "menu_translate",
    )
    translated = MenuNames.model_validate_json(raw).names
    if len(translated) != len(names):
        raise ValueError("번역 결과의 메뉴 개수가 맞지 않아요.")
    return dict(zip(names, translated))
