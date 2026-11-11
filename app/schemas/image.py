from typing import Literal

from pydantic import Field, model_validator

from app.schemas.profile import ProfileModel, ShopProfile


# Normalized 2048px RGBA PNGs can exceed the JPEG upload limit.
MAX_PNG_BASE64 = 24 * 1024 * 1024


class ImageSource(ProfileModel):
    shop_id: int | None = Field(default=None, gt=0)
    profile: ShopProfile | None = None

    @model_validator(mode="after")
    def one_source(self):
        if (self.shop_id is None) == (self.profile is None):
            raise ValueError("저장된 가게 또는 프로필 중 하나만 선택해 주세요.")
        return self


class BackgroundRequest(ImageSource):
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    steps: int = Field(default=25, ge=1, le=100)


class BackgroundResponse(ProfileModel):
    png_base64: str
    seed: int
    prompt: str
    negative_prompt: str
    seconds: float
    max_vram_mb: float


class ComposeRequest(ImageSource):
    mode: Literal["cutout", "original"]
    cutout_png_base64: str | None = Field(default=None, min_length=1, max_length=MAX_PNG_BASE64)
    photo_base64: str | None = Field(default=None, min_length=1, max_length=MAX_PNG_BASE64)
    background_png_base64: str | None = Field(default=None, min_length=1, max_length=MAX_PNG_BASE64)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def photo_for_mode(self):
        if self.mode == "cutout" and (not self.cutout_png_base64 or self.photo_base64):
            raise ValueError("누끼 모드에는 누끼 PNG만 넣어 주세요.")
        if self.mode == "original" and (not self.photo_base64 or self.cutout_png_base64):
            raise ValueError("사진 그대로 모드에는 원본 사진을 넣어 주세요.")
        return self


class ComposeTimes(ProfileModel):
    background: float
    compose: float


class ComposeResponse(ProfileModel):
    composite_png_base64: str
    background_png_base64: str | None
    seed: int | None
    food_bbox: tuple[int, int, int, int] | None
    food_mask_png_base64: str | None
    seconds: ComposeTimes
