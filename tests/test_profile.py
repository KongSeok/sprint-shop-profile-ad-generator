import json

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from app.schemas.profile import ShopProfile


def test_shop_profile_json_schema():
    schema = ShopProfile.model_json_schema()
    assert json.loads(json.dumps(schema, ensure_ascii=False)) == schema
    assert schema["required"] == ["shop_name", "business_type"]
    assert schema["properties"]["shop_name"]["anyOf"] == [
        {"type": "string"}, {"type": "null"}
    ]
    assert schema["properties"]["business_type"]["anyOf"] == [
        {"enum": ["카페", "분식", "고깃집", "베이커리"], "type": "string"},
        {"type": "null"},
    ]
    for field in ("shop_name", "business_type"):
        assert "default" not in schema["properties"][field]
    for incomplete in ({}, {"shop_name": None}, {"business_type": None}):
        with pytest.raises(ValidationError):
            ShopProfile.model_validate(incomplete)
    unnamed = ShopProfile(shop_name=None, business_type=None)
    assert unnamed.shop_name is None and unnamed.business_type is None
    # Verify the SDK can prepare the model for Structured Outputs, offline.
    strict_schema = to_strict_json_schema(ShopProfile)
    for definition in [strict_schema, *strict_schema["$defs"].values()]:
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])
    profile = ShopProfile(shop_name="예시 가게", business_type="카페")
    assert profile.model_dump(exclude={"shop_name", "business_type"}) == {
        "one_line_intro": None, "facts": [], "mood_keywords": [],
        "tone": None, "length": None, "banned_words": [],
        "prohibitions": [], "design": None, "ambiguous": []
    }
