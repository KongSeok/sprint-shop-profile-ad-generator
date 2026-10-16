from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(ProfileModel):
    item: str
    content: str


class Design(ProfileModel):
    main_color: str | None = None
    font_mood: str | None = None


class AmbiguousStatement(ProfileModel):
    sentence: str
    reason: str


class ShopProfile(ProfileModel):
    """사장님이 제공한 정보만 기록하며, 누락된 값은 추측하지 않는다."""

    shop_name: str | None
    business_type: Literal["카페", "분식", "고깃집", "베이커리"] | None
    one_line_intro: str | None = None
    facts: list[Fact] = Field(default_factory=list)
    mood_keywords: list[str] = Field(default_factory=list)
    tone: Literal["존댓말", "반말", "섞음"] | None = None
    length: Literal["짧게", "보통", "길게"] | None = None
    banned_words: list[str] = Field(default_factory=list)
    prohibitions: list[str] = Field(default_factory=list)
    design: Design | None = None
    ambiguous: list[AmbiguousStatement] = Field(default_factory=list)
