from typing import Literal

from pydantic import Field, model_validator

from app.schemas.profile import ProfileModel
from app.services.template_v3 import styles

Style = Literal["classic", "modern", "cozy", "pop", "traditional", "grill"]
AdLayout = Literal["photo_full", "cutout_studio", "receipt", "big_price"]
MenuLayout = Literal["text_list", "premium", "receipt", "big_price"]
Language = Literal["ko", "ko_en", "en_ko"]


class DesignOptions(ProfileModel):
    style: Style
    palette: str
    font: str
    ad_layout: AdLayout
    menu_layout: MenuLayout

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy(cls, data):
        if not isinstance(data, dict) or "style" in data or "tone" not in data:
            return data
        data = dict(data)
        style = {"warm": "cozy", "minimal": "classic", "bold": "pop", "dark": "grill"}.get(data.pop("tone"), "classic")
        data.pop("accent", None)
        data.pop("font_pair", None)
        values = styles()[style]
        data.update(style=style, palette=next(iter(values["palettes"])), font=next(iter(values["fonts"])))
        data["ad_layout"] = "cutout_studio" if data["ad_layout"] == "cutout_badge" else "photo_full"
        data["menu_layout"] = "premium" if data["menu_layout"] == "photo_grid" else "text_list"
        return data

    @model_validator(mode="after")
    def check_catalog(self):
        options = styles()[self.style]
        if self.palette not in options["palettes"] or self.font not in options["fonts"]:
            raise ValueError("스타일에 맞는 팔레트와 글꼴을 골라 주세요.")
        return self


class DesignCandidate(DesignOptions):
    reason: str = Field(min_length=1, max_length=140)


class SavedDesign(DesignCandidate):
    lang: Language = "ko"
    show_origin: bool = False
    source: Literal["추천", "직접", "기본"] = "직접"


class RenderDesign(DesignOptions):
    lang: Language = "ko"
    show_origin: bool = False
    reason: str | None = None
    source: Literal["추천", "직접", "기본"] | None = None
