"""Concepts are presentation preferences, separate from extracted facts."""
import json
from typing import Literal
from pydantic import Field, field_validator, model_validator
from app.core import config
from app.schemas.design import DesignCandidate
from app.schemas.profile import ProfileModel, ShopProfile

DEFAULT_THEMES = ('고깃집', '빵집', '카페', '한식', '일식', '기본')


def allowed_themes() -> list[str]:
    path = config.PROJECT_ROOT / 'templates/themes.json'
    if path.exists():
        themes = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(themes, dict) and themes and 'tones' not in themes:
            return list(dict.fromkeys([*themes, '기본']))
    return list(DEFAULT_THEMES)


def can_suggest(profile: ShopProfile) -> bool:
    return profile.mood_strengths is None and profile.tone is None


class ConceptText(ProfileModel):
    name: str = Field(min_length=1, max_length=10, description='컨셉 이름, 10자 안쪽')
    mood: str = Field(min_length=1, description='분위기 한 줄. 사실이 아닌 표현 방향')
    tone: str = Field(min_length=1, description='말투 한 줄')

    @field_validator('name', 'mood', 'tone')
    @classmethod
    def single_line(cls, value):
        value = value.strip()
        if not value or '\n' in value or '\r' in value:
            raise ValueError('컨셉은 비어 있지 않은 한 줄로 적어 주세요')
        return value

class ConceptCandidate(ConceptText):
    theme: str = Field(description='기존에 저장된 테마 키')

    @field_validator('theme')
    @classmethod
    def valid_theme(cls, value):
        return value if value in allowed_themes() else '기본'


class Concept(ConceptCandidate):
    source: Literal['추천', '직접', '자동']


class ConceptRecommendation(ConceptText):
    design: DesignCandidate


class ModelSuggestions(ProfileModel):
    candidates: list[ConceptRecommendation] = Field(min_length=3, max_length=3)

    @model_validator(mode='after')
    def different_candidates(self):
        if len({candidate.name for candidate in self.candidates}) != len(self.candidates) or len({candidate.mood for candidate in self.candidates}) != len(self.candidates):
            raise ValueError('서로 다른 컨셉 3개가 필요합니다')
        if len({candidate.design.style for candidate in self.candidates}) != len(self.candidates):
            raise ValueError('서로 다른 디자인 스타일이 필요합니다')
        return self


class OriginalPhotoSuggestions(ModelSuggestions):
    candidates: list[ConceptRecommendation] = Field(min_length=2, max_length=2)


class ConceptSuggestions(ModelSuggestions):
    candidates: list[ConceptRecommendation] = Field(min_length=3, max_length=3)
    source: Literal['추천', '기본'] = '추천'
    fallback_reason: str | None = None


class ConceptSuggestRequest(ProfileModel):
    shop_seed: int | None = Field(default=None, gt=0)
    shop_id: int | None = Field(default=None, gt=0)
    profile: ShopProfile | None = None
    menu_name: str | None = Field(default=None, min_length=1)
    photo_menu_count: int = Field(default=0, ge=0, le=12)
    suggest_original: bool = False

    @model_validator(mode='after')
    def one_source(self):
        if (self.shop_id is None) == (self.profile is None):
            raise ValueError('저장된 가게 또는 프로필 중 하나만 선택해 주세요')
        return self
