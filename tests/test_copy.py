import json
from types import SimpleNamespace

import httpx
import pytest
from google import genai
from google.genai.errors import ClientError, ServerError
from pydantic import ValidationError

from app.services import llm_client
from app.core import config
from app.schemas.copy import CopyGenerateRequest, CopyMenu, GeneratedCopy
from app.schemas.profile import ShopProfile
from app.services import copy_generator

REAL_CLIENT = genai.Client


@pytest.fixture
def copy_output():
    return {
        "instagram": {"body": "오늘의 메뉴를 소개해요. 오늘은 어떤 식사를 할지 천천히 골라보세요. 익숙한 하루에 잠깐 쉬어가는 시간을 가져보세요.\n강추라는 표현이 들어갔어요. 메뉴를 살펴보며 마음에 드는 것을 골라보셔도 좋아요.\n편하게 만나보세요. 오늘의 식사도 기분 좋게 즐기시기를 바라요. 부담 없는 마음으로 방문해 주세요.",
                      "hashtags": ["#메뉴", "#소개", "#가게", "#오늘", "#식사"]},
        "delivery_app": {"body": "오늘의 메뉴, 한 끼에 담은 즐거움을 소개해요. 오늘의 식사를 한층 즐겁게 채우는 메뉴예요."},
        "naver_place": {"body": "오늘 메뉴를 소개합니다. 어떤 식사를 할지 고민되는 날이라면 마음에 드는 메뉴를 천천히 살펴보세요. 편하게 찾아주시고 오늘의 식사도 기분 좋게 즐겨주세요. 다시 만나는 시간을 기다리겠습니다. 메뉴에 담긴 가게의 마음도 함께 전해요."},
    }


@pytest.fixture
def copy_mock(gemini_mock, copy_output):
    client = gemini_mock.return_value.__enter__.return_value
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(copy_output, ensure_ascii=False))
    def respond(**kwargs):
        raw = client.models.generate_content.return_value.text
        try:
            data = json.loads(raw)
        except ValueError:
            return SimpleNamespace(text=raw)
        schema = kwargs['config'].response_json_schema
        if 'delivery_app' in schema.get('properties', {}) and 'GeneratedMenuCopy' == schema.get('title'):
            data = {'instagram': data['instagram'], 'delivery_app': {'menu_description': data['delivery_app'].get('body', data['delivery_app'].get('menu_description'))}}
        return SimpleNamespace(text=json.dumps(data, ensure_ascii=False))
    client.models.generate_content.side_effect = respond
    return client


def direct_request(**changes):
    return {"mode": "menu", "profile": {"shop_name": "가게", "business_type": "카페"}, "menu": {"name": "라떼"}, **changes}


@pytest.mark.parametrize("body", [
    {"menu": {"name": "라떼"}},
    direct_request(shop_id=1), direct_request(menu={"name": " "}),
    direct_request(menu={"name": ""}), direct_request(shop_id=0, profile=None),
    direct_request(menu={"name": "라떼", "photo": "not-supported"}),
])
def test_invalid_copy_request_is_422_without_call(api_client, gemini_mock, body):
    assert api_client.post("/copy/generate", json=body).status_code == 422
    gemini_mock.assert_not_called()


def test_menu_trims_and_blank_optionals_are_null():
    menu = CopyMenu(name=" 라떼 ", price=" ", features=" 우유 사용 ")
    assert menu.model_dump() == {"name": "라떼", "price": None, "features": "우유 사용", "this_time": None, "components": None, "origin": None}


def test_prompt_omits_nulls_but_keeps_conflicts_bans_owner_and_menu():
    profile = ShopProfile(shop_name=None, business_type="카페", menus=[{"name": "라떼", "price": None}],
                          needs_check=["월요일 휴무 / 연중무휴"], avoid_expressions=["강추"], owner_phrases=["동네의 쉼터"])
    system, contents = copy_generator.build_copy_prompt(profile, CopyMenu(name="라떼", this_time="이번 주만 1,000원 할인"))
    data = json.loads(contents)
    assert "shop_name" not in data["profile"] and "location" not in data["profile"]
    assert "price" not in data["profile"]["menus"][0] and "price" not in data["menu"]
    assert data["profile"]["needs_check"] == profile.needs_check
    assert data["profile"]["avoid_expressions"] == ["강추"]
    assert data["profile"]["owner_phrases"] == ["동네의 쉼터"]
    assert data["menu"]["this_time"] == "이번 주만 1,000원 할인"
    assert "150~600자" in system and "40~80자" in system and "120~220자" in system


def test_direct_profile_generation_and_code_generated_warnings(api_client, copy_mock, gemini_mock):
    request = direct_request()
    request["profile"]["avoid_expressions"] = ["강추", "역대급", "강추"]
    response = api_client.post("/copy/generate", json=request)
    assert response.status_code == 200
    assert any("강추" in w for w in response.json()["warnings"])
    assert copy_mock.models.generate_content.call_count == 2
    options = copy_mock.models.generate_content.call_args.kwargs["config"]
    assert options.temperature == 0.7 and options.thinking_config.thinking_level.value == "MEDIUM"
    assert options.response_mime_type == "application/json"
    assert "warnings" not in options.response_json_schema["properties"]
    assert gemini_mock.call_args.kwargs["http_options"].timeout == config.GEMINI_TIMEOUT_MS
    assert gemini_mock.call_args.kwargs["http_options"].retry_options.attempts == 1


def test_saved_shop_generation_uses_saved_profile(api_client, copy_mock):
    saved = api_client.post("/profile/save", json={
        "profile": {"shop_name": "저장 가게", "business_type": "카페"}, "source_text": "원문", "prompt_version": "v2",
    })
    shop_id = saved.json()["shop_id"]
    result = api_client.post("/copy/generate", json={"mode": "menu", "shop_id": shop_id, "menu": {"name": "라떼"}})
    assert result.status_code == 200
    data = json.loads(copy_mock.models.generate_content.call_args.kwargs["contents"])
    assert data["profile"]["shop_name"] == "저장 가게"
    assert data["menu"]["name"] == "라떼"


def test_unknown_shop_is_404_without_gemini(api_client, gemini_mock):
    response = api_client.post("/copy/generate", json={"mode": "menu", "shop_id": 999, "menu": {"name": "라떼"}})
    assert response.status_code == 404 and response.json()["detail"] == "저장된 가게를 찾을 수 없습니다"
    gemini_mock.assert_not_called()


@pytest.mark.parametrize("status", [429, 503, 504])
def test_transient_errors_return_retry_message_without_server_retry(api_client, copy_mock, status, monkeypatch):
    copy_mock.models.generate_content.side_effect = ServerError(status, {"error": {"message": "test-only-gemini-key"}})
    delays = []
    monkeypatch.setattr("app.services.llm_client.sleep", delays.append)
    response = api_client.post("/copy/generate", json=direct_request())
    assert response.status_code == 503
    assert response.json()["detail"]["message"] == "잠시 후 다시 눌러 주세요"
    assert "test-only-gemini-key" not in response.text
    assert copy_mock.models.generate_content.call_count == (3 if status >= 500 else 1)
    assert delays == ([5, 15] if status >= 500 else [])


def test_other_upstream_error_redacts_key(api_client, copy_mock):
    copy_mock.models.generate_content.side_effect = ClientError(400, {"error": {"message": "bad test-only-gemini-key"}})
    result = api_client.post("/copy/generate", json=direct_request())
    assert result.status_code == 502 and "test-only-gemini-key" not in result.text
    assert "[REDACTED]" in result.json()["detail"]["message"]


def test_missing_key_and_bad_response_are_safe(api_client, copy_mock, monkeypatch):
    copy_mock.models.generate_content.return_value = SimpleNamespace(text="{bad JSON")
    result = api_client.post("/copy/generate", json=direct_request())
    assert result.status_code == 502 and result.json()["detail"]["code"] == "COPY_VALIDATION_FAILED"
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert api_client.post("/copy/generate", json=direct_request()).status_code == 503


def test_warnings_include_hashtags_and_are_empty_without_match(copy_output):
    copy_output["instagram"]["hashtags"][0] = "#역대급"
    generated = GeneratedCopy.model_validate(copy_output)
    assert copy_generator.banned_expression_warnings(ShopProfile(shop_name=None, business_type=None), generated) == []
    assert copy_generator.banned_expression_warnings(ShopProfile(shop_name=None, business_type=None, avoid_expressions=["역대급"]), generated)


@pytest.mark.parametrize("field,value", [
    ("body", "한 줄"), ("hashtags", ["#하나"]),
    ("hashtags", ["없음", "#둘", "#셋", "#넷", "#다섯"]),
])
def test_invalid_instagram_shape_is_rejected(copy_output, field, value):
    copy_output["instagram"][field] = value
    with pytest.raises(ValidationError):
        GeneratedCopy.model_validate(copy_output)


def test_real_sdk_serializes_copy_schema_without_network(api_client, copy_output, monkeypatch):
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps({"instagram":copy_output["instagram"],"delivery_app":{"menu_description":copy_output["delivery_app"]["body"]}})}]}, "finishReason": "STOP"}]})

    def client(**kwargs):
        kwargs["http_options"].httpx_client = httpx.Client(transport=httpx.MockTransport(handle))
        return REAL_CLIENT(**kwargs)

    monkeypatch.setattr(llm_client.genai, "Client", client)
    assert api_client.post("/copy/generate", json=direct_request()).status_code == 200
    assert len(calls) <= 2 and calls[0]["generationConfig"]["temperature"] == 0.7
    assert calls[0]["generationConfig"]["thinkingConfig"] == {"thinking_level": "MEDIUM"}
