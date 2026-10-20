import json

import pytest
from pydantic import ValidationError

from app.schemas.profile import Menu, ShopProfile


def test_shop_profile_json_schema():
    schema = ShopProfile.model_json_schema()
    assert json.loads(json.dumps(schema, ensure_ascii=False)) == schema
    assert schema["required"] == ["shop_name", "business_type"]
    for name in ("shop_name", "business_type"):
        assert schema["properties"][name]["anyOf"] == [{"type": "string"}, {"type": "null"}]
        assert "default" not in schema["properties"][name]
    for model in (ShopProfile, Menu):
        assert model.model_json_schema()["additionalProperties"] is False
        assert all(field.description for field in model.model_fields.values())


def test_unknown_information_is_null():
    assert all(value is None for value in ShopProfile(shop_name=None, business_type=None).model_dump().values())


@pytest.mark.parametrize("data", [{}, {"shop_name": None}, {"business_type": None}])
def test_identity_keys_are_required_but_nullable(data):
    with pytest.raises(ValidationError):
        ShopProfile.model_validate(data)


def test_preserves_conditions_and_owner_phrases():
    profile = ShopProfile(
        shop_name=None, business_type="동네 식당",
        menus=[Menu(name="정식", price="평일 점심만 9천원")],
        parking="주말 1시간만 무료", owner_phrases=["우주 최고 맛집"],
        other_info=["국내산 한돈만 사용", "창가 좌석 사진 요청"],
        needs_check=["월요일 쉼 / 연중무휴: 휴무일 확인"],
    )
    assert ShopProfile.model_validate_json(profile.model_dump_json()) == profile


@pytest.mark.parametrize("changes", [
    {"menus": [{"name": "라떼", "price": 5000}]}, {"menus": [{"price": "5천원"}]},
    {"owner_phrases": "좋아요"}, {"hours": 10}, {"unknown": "추가 필드"},
    {"other_info": "예약 가능"}, {"other_info": [123]},
])
def test_rejects_wrong_types_and_extra_fields(changes):
    with pytest.raises(ValidationError):
        ShopProfile.model_validate({"shop_name": None, "business_type": None, **changes})
