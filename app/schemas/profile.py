from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Menu(ProfileModel):
    name: str = Field(description="대표 메뉴 이름. 사장님이 쓴 원문 그대로")
    price: str | None = Field(default=None, description="메뉴 가격. 단위와 적용 조건까지 원문 그대로, 없으면 null")


class ShopProfile(ProfileModel):
    """사장님 원문을 보존하며, 업종은 메뉴로 분명할 때만 판단한다."""

    shop_name: str | None = Field(description="가게 이름. 글에 없으면 null, 지어내지 않기")
    business_type: str | None = Field(description="업종이 글에 직접 없어도 메뉴로 분명하면 적고(예: 삼겹살·항정살 → 고깃집), 애매하면 null")
    location: str | None = Field(default=None, description="위치. 주소와 찾아오는 조건을 원문 그대로")
    hours: str | None = Field(default=None, description="영업시간. 요일, 브레이크 타임 등 조건까지 원문 그대로")
    closed_days: str | None = Field(default=None, description="휴무일. 예외와 조건까지 원문 그대로")
    menus: list[Menu] | None = Field(default=None, description="대표 메뉴·가격. 글에 있는 메뉴만 기록하고 없으면 null")
    takeout_delivery: str | None = Field(default=None, description="포장·배달. 가능 여부와 최소 금액 등 조건까지 원문 그대로")
    parking: str | None = Field(default=None, description="주차. 가능 여부, 시간, 요금과 조건까지 원문 그대로")
    mood_strengths: str | None = Field(default=None, description="분위기·강점. 사장님이 쓴 표현만 원문 그대로")
    tone: str | None = Field(default=None, description="원하는 말투. 사장님이 지정하지 않으면 null")
    avoid_expressions: list[str] | None = Field(default=None, description="피할 표현. 사장님이 명시한 표현만 기록")
    owner_phrases: list[str] | None = Field(default=None, description="사장님 꾸밈말 원문 그대로. 사실로 단정하거나 다른 표현으로 고치지 않기")
    needs_check: list[str] | None = Field(default=None, description="글 안에서 부딪히는 내용. 양쪽 내용을 보존하고 충돌마다 한 줄로 기록")

    other_info: list[str] | None = Field(default=None, description="기타 정보. 원산지·예약·좌석·사진 요청처럼 다른 칸에 안 맞는 사실, 원문 그대로")


class ProfileExtractRequest(ProfileModel):
    text: str = Field(min_length=1, description="사장님 소개 글")
    prompt_version: Literal["v1", "v2"] = "v2"

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("사장님 소개 글을 입력해 주세요.")
        return value
