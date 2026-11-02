from typing import Literal
from pydantic import Field, field_validator, model_validator

from app.schemas.concept import Concept
from app.schemas.profile import ProfileModel, ShopProfile


class CopyMenu(ProfileModel):
    name: str = Field(min_length=1, description="메뉴 이름")
    price: str | None = Field(default=None, description="가격. 단위와 조건 포함")
    features: str | None = Field(default=None, description="메뉴 특징. 입력된 사실만 사용")
    this_time: str | None = Field(default=None, description="이번만 요청. 기간과 조건을 그대로 사용")

    @field_validator("name", "price", "features", "this_time")
    @classmethod
    def trim_input(cls, value, info):
        if value is None:
            return None
        value = value.strip()
        if not value and info.field_name == "name":
            raise ValueError("메뉴 이름을 적어 주세요")
        return value or None


class CopyGenerateRequest(ProfileModel):
    shop_id: int | None = Field(default=None, gt=0)
    profile: ShopProfile | None = None
    menu: CopyMenu
    concept: Concept | None = None
    prompt_version: Literal["v1", "v2"] = "v2"
    use_examples: bool = True

    @model_validator(mode="after")
    def exactly_one_profile_source(self):
        if (self.shop_id is None) == (self.profile is None):
            raise ValueError("저장된 가게 또는 프로필 중 하나만 선택해 주세요")
        return self


class InstagramCopy(ProfileModel):
    body: str = Field(min_length=1, description="인스타그램 문구. 비어 있지 않은 3~6줄")
    hashtags: list[str] = Field(min_length=5, max_length=10, description="#을 포함한 해시태그 5~10개")

    @field_validator("body")
    @classmethod
    def check_lines(cls, value):
        value = value.strip()
        if not 3 <= len([line for line in value.splitlines() if line.strip()]) <= 6:
            raise ValueError("인스타그램 문구는 3~6줄이어야 합니다")
        return value

    @field_validator("hashtags")
    @classmethod
    def check_hashtags(cls, value):
        if any(not item.startswith("#") or len(item) < 2 or any(char.isspace() for char in item) for item in value):
            raise ValueError("해시태그마다 #을 붙이고 공백 없이 작성해 주세요")
        return value


class DeliveryCopy(ProfileModel):
    body: str = Field(min_length=1, max_length=80, description="배달앱 메뉴 설명. 1~2문장, 공백 포함 80자 안쪽")


class NaverPlaceCopy(ProfileModel):
    body: str = Field(min_length=1, description="네이버 플레이스 소식 글. 3~5문장")


class GeneratedCopy(ProfileModel):
    instagram: InstagramCopy
    delivery_app: DeliveryCopy
    naver_place: NaverPlaceCopy


class TextCopy(ProfileModel):
    body: str = Field(min_length=1)


class InstagramResult(TextCopy):
    hashtags: list[str]


class InstagramCopyV2(ProfileModel):
    body: str = Field(min_length=150, max_length=600, description="인스타그램 본문. 공백·줄바꿈 포함 150~600자. 문장·줄 수 제한 없음")
    hashtags: list[str] = Field(min_length=5, max_length=15, description="#을 포함한 해시태그 5~15개")

    @field_validator("hashtags")
    @classmethod
    def check_hashtags(cls, value):
        return InstagramCopy.check_hashtags(value)


class DeliveryCopyV2(ProfileModel):
    body: str = Field(min_length=30, max_length=200, description="배달앱 본문. 공백·줄바꿈 포함 30~200자")


class NaverPlaceCopyV2(ProfileModel):
    body: str = Field(min_length=100, max_length=500, description="네이버 플레이스 본문. 공백·줄바꿈 포함 100~500자")


class GeneratedCopyV2(ProfileModel):
    instagram: InstagramCopyV2
    delivery_app: DeliveryCopyV2
    naver_place: NaverPlaceCopyV2


def generated_copy_model(prompt_version):
    return GeneratedCopyV2 if prompt_version == "v2" else GeneratedCopy


class CopyGenerateResponse(ProfileModel):
    # Each version is validated by its own generation model before conversion.
    instagram: InstagramResult
    delivery_app: TextCopy
    naver_place: TextCopy
    warnings: list[str] = Field(default_factory=list, description="서버가 검사한 경고")
    example_ids: list[str] = Field(default_factory=list, description="사용한 예시 ID")
