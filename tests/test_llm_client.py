import json
from unittest.mock import Mock

import httpx
import pytest

from app.core import config
from app.services import llm_client


SCHEMA = {"type": "object", "properties": {"name": {"type": "string"},
          "tags": {"type": "array", "items": {"type": "string"}, "default": []}}, "required": ["name"]}


def test_strict_schema_does_not_mutate_original():
    schema = llm_client.strict_schema(SCHEMA)
    assert schema["required"] == ["name", "tags"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["tags"]["anyOf"][1] == {"type": "null"}
    assert SCHEMA["properties"]["tags"]["default"] == []


def setup_openai(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(config, "OPENAI_MODEL", "gpt-5-mini")
    delay = Mock()
    monkeypatch.setattr(llm_client, "sleep", delay)
    return delay


def test_openai_strict_retry_and_usage(monkeypatch):
    sleep = setup_openai(monkeypatch)
    responses = [
        httpx.Response(500, json={"error":{"message":"busy"}}),
        httpx.Response(429, json={"error":{"code":"rate_limit_exceeded"}}),
        httpx.Response(200, json={"status":"completed","usage":{"input_tokens":15,"output_tokens":6},
            "output":[{"content":[{"type":"output_text","text":'{"name":"shop","tags":null}'}]}]}),
    ]
    send = Mock(side_effect=responses)
    monkeypatch.setattr(llm_client.httpx, "post", send)
    assert json.loads(llm_client.generate_json("system", "user", SCHEMA, 0.7, "test")) == {"name":"shop"}
    assert [call.args[0] for call in sleep.call_args_list] == [5,15]
    payload = send.call_args.kwargs["json"]
    assert payload["instructions"] == "system" and payload["input"] == "user"
    assert payload["text"]["format"]["strict"] is True and "temperature" not in payload
    rows = [json.loads(line) for line in llm_client.LOG_PATH.read_text().splitlines()]
    assert [row["code"] for row in rows] == ["HTTP_500","rate_limit_exceeded","ok"]
    assert rows[-1]["input_tokens"] == 15 and rows[-1]["output_tokens"] == 6


def test_quota_immediately_uses_default_design(monkeypatch, api_client):
    sleep = setup_openai(monkeypatch)
    send = Mock(return_value=httpx.Response(429, json={"error":{"code":"insufficient_quota"}}))
    monkeypatch.setattr(llm_client.httpx, "post", send)
    result = api_client.post("/profile/suggest-concept", json={"profile":{"shop_name":"가게","business_type":"카페"}})
    assert result.json()["source"] == "기본"
    assert result.json()["fallback_reason"] == llm_client.QUOTA_MESSAGE
    send.assert_called_once()
    sleep.assert_not_called()


def test_gemini_uses_original_schema(gemini_mock):
    llm_client.generate_json("system", "user", SCHEMA, 0.7, "test")
    call = gemini_mock.return_value.__enter__.return_value.models.generate_content.call_args.kwargs
    assert call["contents"] == "user"
    assert call["config"].response_json_schema == SCHEMA


def test_clean_json_removes_invisible_characters_in_escaped_nested_values():
    raw = r'{"a\u200b":["메\u200c뉴",{"x":"\ufeff값\u200d\u2060"}]}'
    assert json.loads(llm_client.clean_json(raw)) == {"a": ["메뉴", {"x": "값"}]}
