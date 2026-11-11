"""Design catalog and accessible CSS color roles."""
from app.core.config import PROJECT_ROOT
from app.schemas.design import SavedDesign
from app.services.template_v3 import CATEGORY_STYLES, styles
from app.services.copy_examples import business_category

def catalog(root=PROJECT_ROOT / "templates"):
    return styles(root)


def luminance(color):
    channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

def contrast(a, b):
    dark, light = sorted((luminance(a), luminance(b)))
    return (light + 0.05) / (dark + 0.05)

def variables(design, options):
    palette = options[design.style]["palettes"][design.palette]
    return {"color_bg": palette["bg"], "color_main": palette["ink"], "color_accent": palette["accent"],
            "band_start": palette["bg"], "band_end": palette["bg2"], "band_ink": palette["ink"],
            "accent_ink": palette["accent_ink"], "font_title": "Noto Sans KR", "font_body": "Noto Sans KR"}


def text_pairs(css):
    return [(css['color_main'], css['color_bg']),
            (css['band_ink'], css['band_start']), (css['band_ink'], css['band_end']),
            (css['accent_ink'], css['color_accent'])]

def default_design(business_type, style=None):
    category = business_category(business_type)
    style = style or CATEGORY_STYLES.get(category, "classic")
    options = styles()[style]
    return SavedDesign(style=style, palette=next(iter(options["palettes"])), font=next(iter(options["fonts"])),
                       ad_layout="photo_full", menu_layout="text_list", source="기본",
                       reason=f"{category or '가게'} 메뉴에 맞춘 기본 디자인입니다.")
