from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.concept import Concept
from app.schemas.profile import ProfileModel, ShopProfile

REQUIRED_MESSAGE = "가게 이름과 업종은 꼭 적어 주세요"


def normalize_saved_profile(profile: ShopProfile) -> ShopProfile:
    values = profile.model_dump()
    for name, value in values.items():
        if isinstance(value, str):
            values[name] = value.strip() or None
        elif isinstance(value, list) and name != "menus":
            values[name] = [item.strip() for item in value if item.strip()] or None
    menus = []
    for menu in values.get("menus") or []:
        name = menu["name"].strip()
        price = (menu.get("price") or "").strip() or None
        if not name and not price:
            continue
        if not name:
            raise ValueError("메뉴 이름을 적어 주세요")
        menus.append({"name": name, "price": price})
    values["menus"] = menus or None
    if not values["shop_name"] or not values["business_type"]:
        raise ValueError(REQUIRED_MESSAGE)
    return ShopProfile.model_validate(values)


class ProfileSaveRequest(ProfileModel):
    shop_id: int | None = Field(default=None, gt=0)
    profile: ShopProfile
    concept: Concept | None = None
    source_text: str
    prompt_version: Literal["v1", "v2"] = "v2"

    @model_validator(mode="before")
    @classmethod
    def require_shop_identity(cls, value):
        if isinstance(value, dict) and isinstance(value.get("profile"), dict):
            profile = value["profile"]
            if any(not isinstance(profile.get(key), str) or not profile[key].strip()
                   for key in ("shop_name", "business_type")):
                raise ValueError(REQUIRED_MESSAGE)
        return value

    @field_validator("profile")
    @classmethod
    def clean_profile(cls, profile: ShopProfile) -> ShopProfile:
        return normalize_saved_profile(profile)


class ProfileSaveResponse(ProfileModel):
    shop_id: int


class ShopListItem(ProfileModel):
    id: int
    shop_name: str
    business_type: str
    updated_at: str


class SavedShop(ProfileModel):
    shop_id: int
    profile: ShopProfile
    concept: Concept | None = None
    source_text: str
    prompt_version: Literal["v1", "v2"]
    created_at: str
    updated_at: str
