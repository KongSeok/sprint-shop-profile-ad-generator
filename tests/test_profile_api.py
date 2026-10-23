import json
from types import SimpleNamespace

import pytest
import httpx
from google import genai
from google.genai import errors

from app.core import config
from app.services import profile_extractor
from app.services.fewshot_loader import load_fewshot_examples

REAL_GENAI_CLIENT = genai.Client


def test_real_sdk_serializes_pydantic_schema_with_mock_transport(api_client, monkeypatch):
    """Exercise SDK conversion too, while all HTTP is intercepted locally."""
    sent = []

    def respond(request):
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(200, json={
            "candidates": [{
                "content": {"role": "model", "parts": [{"text": json.dumps({
                    "shop_name": None, "business_type": None, "parking": "주말만 무료",
                    "other_info": ["국내산 한돈만 사용", "고기 사진 요청"],
                })}]},
                "finishReason": "STOP",
            }],
        })

    def offline_client(**kwargs):
        kwargs["http_options"].httpx_client = httpx.Client(transport=httpx.MockTransport(respond))
        return REAL_GENAI_CLIENT(**kwargs)

    monkeypatch.setattr(profile_extractor.genai, "Client", offline_client)
    response = api_client.post("/profile/extract", json={"text": "주말만 무료", "prompt_version": "v1"})
    assert response.status_code == 200
    assert response.json()["parking"] == "주말만 무료"
    assert response.json()["other_info"] == ["국내산 한돈만 사용", "고기 사진 요청"]
    assert len(sent) == 1
    generation = sent[0]["generationConfig"]
    assert generation["responseMimeType"] == "application/json"
    assert "responseSchema" not in generation
    assert "additional_properties" not in json.dumps(generation)
    assert generation["responseJsonSchema"]["additionalProperties"] is False
    assert "shop_name" in generation["responseJsonSchema"]["properties"]
    assert "other_info" in generation["responseJsonSchema"]["properties"]


def test_health_still_works(api_client):
    assert api_client.get("/health").json() == {"status": "ok"}


def test_v1_calls_gemini_with_schema_and_low_temperature(api_client, gemini_mock):
    result = api_client.post("/profile/extract", json={"text": "주말만 주차 가능", "prompt_version": "v1"})
    assert result.status_code == 200
    assert all(value is None for value in result.json().values())
    assert gemini_mock.call_args.kwargs["vertexai"] is False
    call = gemini_mock.return_value.__enter__.return_value.models.generate_content.call_args.kwargs
    assert call["model"] == "gemini-3.8-flash"
    assert call["contents"] == "주말만 주차 가능"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_json_schema == profile_extractor.ShopProfile.model_json_schema()
    assert 0 <= call["config"].temperature <= 0.2


def test_default_v2_uses_train_examples(api_client, gemini_mock, fewshot_data, monkeypatch):
    monkeypatch.setattr(profile_extractor, "load_fewshot_examples", lambda: load_fewshot_examples(fewshot_data))
    assert api_client.post("/profile/extract", json={"text": "소개 글"}).status_code == 200
    prompt = gemini_mock.return_value.__enter__.return_value.models.generate_content.call_args.kwargs["config"].system_instruction
    assert "EVAL_MUST_NEVER_APPEAR" not in prompt
    assert "EVAL_GOLD_MUST_NEVER_APPEAR" not in prompt
    for value in (1, 7, 13, 19, 25):
        assert f"테스트 원문 {value}" in prompt


@pytest.mark.parametrize("payload", [
    {}, {"text": ""}, {"text": " \n"}, {"text": 123},
    {"text": "소개", "prompt_version": "v3"}, {"text": "소개", "extra": True},
])
def test_invalid_request_never_calls_gemini(api_client, gemini_mock, payload):
    assert api_client.post("/profile/extract", json=payload).status_code == 422
    gemini_mock.assert_not_called()


def test_missing_key_has_clear_error(api_client, gemini_mock, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", " ")
    response = api_client.post("/profile/extract", json={"text": "소개", "prompt_version": "v1"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "GEMINI_KEY_MISSING"
    gemini_mock.assert_not_called()


@pytest.mark.parametrize("blank", [False, True])
def test_unready_v2_never_calls_gemini(api_client, gemini_mock, tmp_path, monkeypatch, blank):
    data_dir = tmp_path / "data"
    if blank:
        (data_dir / "samples").mkdir(parents=True)
        (data_dir / "samples" / "answer_profiles_gold.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(profile_extractor, "load_fewshot_examples", lambda: load_fewshot_examples(data_dir))
    response = api_client.post("/profile/extract", json={"text": "소개"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "FEWSHOT_NOT_READY"
    assert "answer_profiles_gold.jsonl" in response.json()["detail"]["message"]
    gemini_mock.assert_not_called()


def test_gemini_failure_is_visible_without_key_leak(api_client, gemini_mock):
    client = gemini_mock.return_value.__enter__.return_value
    client.models.generate_content.side_effect = errors.ClientError(
        429, {"error": {"message": "Quota exceeded test-only-gemini-key", "status": "RESOURCE_EXHAUSTED"}}
    )
    response = api_client.post("/profile/extract", json={"text": "소개", "prompt_version": "v1"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "GEMINI_CALL_FAILED"
    assert "429" in response.text and "Quota exceeded" in response.text
    assert "test-only-gemini-key" not in response.text


def test_transport_failure_has_clear_error(api_client, gemini_mock):
    gemini_mock.return_value.__enter__.return_value.models.generate_content.side_effect = TimeoutError("test-only-gemini-key")
    response = api_client.post("/profile/extract", json={"text": "소개", "prompt_version": "v1"})
    assert response.status_code == 502
    assert "TimeoutError" in response.json()["detail"]["message"]
    assert "test-only-gemini-key" not in response.text


@pytest.mark.parametrize("text", ["not json", "{}", json.dumps({"shop_name": 123, "business_type": None})])
def test_invalid_profile_has_validation_error(api_client, gemini_mock, text):
    gemini_mock.return_value.__enter__.return_value.models.generate_content.return_value = SimpleNamespace(text=text)
    response = api_client.post("/profile/extract", json={"text": "소개", "prompt_version": "v1"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "PROFILE_VALIDATION_FAILED"


def test_empty_response_has_clear_error(api_client, gemini_mock):
    gemini_mock.return_value.__enter__.return_value.models.generate_content.return_value = SimpleNamespace(text=None)
    response = api_client.post("/profile/extract", json={"text": "소개", "prompt_version": "v1"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "GEMINI_EMPTY_RESPONSE"
