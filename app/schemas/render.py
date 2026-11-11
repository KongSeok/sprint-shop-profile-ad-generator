from pydantic import Field, field_validator, model_validator
from app.schemas.profile import ProfileModel, ShopProfile
from app.schemas.copy import CopyMenu
from app.schemas.design import RenderDesign


class RenderSource(ProfileModel):
    shop_id: int | None = Field(default=None, gt=0)
    profile: ShopProfile | None = None
    template: str | None = None
    design: RenderDesign | None = None
    theme: str | None = None

    @model_validator(mode='after')
    def one_source(self):
        if (self.shop_id is None) == (self.profile is None):
            raise ValueError('저장된 가게 또는 프로필 중 하나만 선택해 주세요')
        return self


class AdCardRequest(RenderSource):
    menu: CopyMenu
    headline: str = ''
    body: str = ""
    photo_url: str | None = Field(default=None, max_length=24 * 1024 * 1024)
    cutout_url: str | None = Field(default=None, max_length=24 * 1024 * 1024)
    menu_name_en: str | None = None
    origin: str | None = None


    background_url: str | None = Field(default=None, max_length=24 * 1024 * 1024)
    food_mask_url: str | None = Field(default=None, max_length=24 * 1024 * 1024)
    suggest_original: bool = False


class RenderResponse(ProfileModel):
    png_base64: str
    warnings: list[str]


class BoardMenu(ProfileModel):
    name: str = Field(min_length=1)
    price: str | None = None
    note: str | None = None
    name_en: str | None = None
    origin: str | None = None
    photo_url: str | None = Field(default=None, max_length=24 * 1024 * 1024)

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
