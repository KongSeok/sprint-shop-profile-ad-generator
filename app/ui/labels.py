STYLES = {
    "classic": "클래식", "modern": "모던", "cozy": "포근한",
    "pop": "발랄한", "traditional": "전통", "grill": "숯불",
}
AD_LAYOUTS = {
    "photo_full": "사진 꽉 차게", "cutout_studio": "음식만 크게",
    "receipt": "영수증", "big_price": "가격 크게",
}
MENU_LAYOUTS = {
    "text_list": "글자 목록", "premium": "사진 넣은 고급형",
    "receipt": "영수증", "big_price": "가격 크게",
}
CUTOUT_MODES = {"cutout": "배경 지우기", "original": "사진 그대로"}


def shop_label(shop):
    return f"{shop['shop_name']} · {shop['business_type']}"
