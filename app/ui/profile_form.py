"""Pure conversion helpers; no network, Streamlit, or database access."""

import math

from app.schemas.profile import ShopProfile

TEXT_FIELDS = {
    "shop_name": "가게 이름 (필수)", "business_type": "업종 (필수)",
    "location": "위치", "hours": "영업시간", "closed_days": "휴무일",
    "takeout_delivery": "포장·배달", "parking": "주차",
    "mood_strengths": "분위기·강점", "tone": "원하는 말투",
}
LIST_FIELDS = {"avoid_expressions": "피할 표현", "owner_phrases": "사장님 꾸밈말", "other_info": "기타 정보"}


def blank_to_none(value) -> str | None:
    if value is None or isinstance(value, float) and math.isnan(value):
        return None
    return str(value).strip() or None


def lines_to_list(value: str | None) -> list[str] | None:
    return [line.strip() for line in (value or "").splitlines() if line.strip()] or None


def list_to_lines(value: list[str] | None) -> str:
    return "\n".join(item.strip() for item in value or [] if item.strip())


def table_to_menus(rows) -> list[dict] | None:
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict("records")
    menus = []
    for row in rows or []:
        name = blank_to_none(row.get("name"))
        price = blank_to_none(row.get("price"))
        if not name and not price:
            continue
        if not name:
            raise ValueError("가격을 적은 줄에는 메뉴 이름도 적어 주세요")
        menus.append({"name": name, "price": price})
    return menus or None


def form_to_profile(values: dict, menu_rows, needs_check: list[str] | None = None) -> dict:
    data = {key: blank_to_none(values.get(key)) for key in TEXT_FIELDS}
    data.update({key: lines_to_list(values.get(key)) for key in LIST_FIELDS})
    data["menus"] = table_to_menus(menu_rows)
    data["needs_check"] = lines_to_list(list_to_lines(needs_check))
    return ShopProfile.model_validate(data).model_dump()
