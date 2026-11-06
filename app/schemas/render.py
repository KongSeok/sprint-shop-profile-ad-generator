from pydantic import Field, field_validator, model_validator
from app.schemas.profile import ProfileModel, ShopProfile
from app.schemas.copy import CopyMenu


class RenderSource(ProfileModel):
    shop_id: int | None = Field(default=None, gt=0)
    profile: ShopProfile | None = None
    template: str = 'placeholder'
    theme: str | None = None

    @model_validator(mode='after')
    def one_source(self):
        if (self.shop_id is None) == (self.profile is None):
            raise ValueError('저장된 가게 또는 프로필 중 하나만 선택해 주세요')
        return self


class AdCardRequest(RenderSource):
    menu: CopyMenu
    headline: str = Field(min_length=1)
    body: str


class RenderResponse(ProfileModel):
    png_base64: str
    warnings: list[str]


class BoardMenu(ProfileModel):
    name: str = Field(min_length=1)
    price: str | None = None
    note: str | None = None

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('메뉴 이름을 입력해 주세요')
        return value.strip()


class MenuBoardRequest(RenderSource):
    menus: list[BoardMenu] | None = None

    @field_validator('menus')
    @classmethod
    def maximum_menus(cls, value):
        if value is not None and len(value) > 12:
            raise ValueError('메뉴는 12개까지')
        return value
