"""Context adapter for the unmodified Claude v3 HTML/CSS."""
import json
import re
from functools import lru_cache

from app.core.config import PROJECT_ROOT
from app.services.copy_examples import business_category

ROOT = PROJECT_ROOT / "templates"
LAYOUTS = {
    ("ad_card", "photo_full"), ("ad_card", "cutout_studio"),
    ("menu_board", "text_list"), ("menu_board", "premium"),
}
LAYOUTS |= {(kind, name) for kind in ("ad_card", "menu_board") for name in ("receipt", "big_price")}
CATEGORY_STYLES = {"카페": "cozy", "빵집": "classic", "한식": "traditional",
                   "고깃집": "grill", "일식": "modern", "분식": "pop"}
LABELS = {"카페": "Cafe", "빵집": "Bakery", "한식": "Korean", "고깃집": "Charcoal grill",
          "일식": "Japanese", "분식": "Korean snacks"}


@lru_cache
def styles(root=ROOT):
    return json.loads((root / "styles.json").read_text(encoding="utf-8"))


def context(style, palette, font, lang, root=ROOT):
    settings = styles(root)[style]
    p = settings["palettes"][palette]
    f = settings["fonts"][font]
    variables = {key: p[key] for key in ("bg", "bg2", "ink", "sub", "line", "accent")}
    from app.services.design_options import contrast, luminance

    if luminance(p["bg"]) >= luminance(p["ink"]):
        paper, ink, reference = f'color-mix(in srgb,{p["bg"]} 18%,#FFFEFA)', p["ink"], "#FBF8F0"
    else:
        paper, ink, reference = p["ink"], p["bg"], p["ink"]
    variables.update({"paper": paper, "paper-ink": ink,
                      "paper-sub": f"color-mix(in srgb,{ink} 72%,{reference})",
                      "paper-accent": p["accent"] if contrast(p["accent"], reference) >= 3 else ink})
    variables.update({
        "accent-ink": p["accent_ink"], "font-title": json.dumps(f["title"], ensure_ascii=False),
        "title-weight": f["title_weight"], "font-body": json.dumps(f["body"], ensure_ascii=False),
        "font-script": json.dumps(f["script"], ensure_ascii=False), "script-style": f["script_style"],
        "title-scale": f["title_scale"], "title-track": f["title_track"],
        "shop-track": settings["shop_track"], "radius": settings["radius"],
        "font-latin": json.dumps(f["latin"], ensure_ascii=False),
        "latin-style": "italic" if f["latin"] in ("Cormorant Garamond", "Playfair Display", "DM Serif Display") else "normal",
        "body-weight": f["body_weight"], "glyph": f.get("glyph", 1),
    })
    return dict(
        theme_css=":root{" + ";".join(f"--{key}:{value}" for key, value in variables.items()) + "}",
        style=style, deco=settings["deco"], photo_mode=p["photo"], price_style=settings["price"],
        label_lang="en" if lang == "en_ko" else settings["label_lang"],
        base_css=(root / "base.css").read_text(encoding="utf-8"),
        fit_js=(root / "fit.js").read_text(encoding="utf-8"), lang=lang,
    )


def split_price(value):
    match = re.match(r"^(.*?)\s*([\d,]+)\s*원$", value or "")
    return (match[1].strip(), match[2]) if match else ("", None)


def names(lang, ko, en):
    if lang == "ko_en" and en:
        return ko, en, "en"
    if lang == "en_ko" and en:
        return en, ko, "ko"
    return ko, None, None


def render_context(values, business_type, design=None, root=ROOT):
    category = business_category(business_type)
    style = getattr(design, "style", None) or CATEGORY_STYLES.get(category, "classic")
    settings = styles(root)[style]
    palette = getattr(design, "palette", None) or next(iter(settings["palettes"]))
    font = getattr(design, "font", None) or next(iter(settings["fonts"]))
    lang = getattr(design, "lang", "ko")
    output = {
        "photo_url": "", "cutout_url": "", "category_ko": category or "",
        "category_en": LABELS.get(category, ""), **values,
    }
    for key in ("photo_url", "cutout_url"):
        output[key] = output[key] or ""
    if "menu_name" in values:
        output["price_pre"], output["price_num"] = split_price(values.get("price"))
        output["main_name"], output["sub_name"], output["sub_lang"] = names(
            lang, values["menu_name"], values.get("menu_name_en"),
        )
    if "menus" in values:
        output["menus"] = []
        for row in values["menus"]:
            main, sub, sub_lang = names(lang, row["name"], row.get("name_en"))
            price_pre, price_num = split_price(row.get("price"))
            output["menus"].append(dict(row, main=main, sub=sub, sub_lang=sub_lang,
                                        price_pre=price_pre, price_num=price_num))
    return {**output, **context(style, palette, font, lang, root)}
