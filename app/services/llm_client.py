"""JSON generation and usage accounting for the configured LLM."""
import json
import logging
import re
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter, sleep

import httpx
from google import genai
from google.genai import errors, types

from app.core import config
from app.services.gemini_retry import OVERLOAD_DELAYS

LOG_PATH = config.PROJECT_ROOT / "logs" / "llm_calls.jsonl"
QUOTA_MESSAGE = "AI 서비스 잔액 또는 사용 한도가 소진됐어요."
logger = logging.getLogger(__name__)


class LLMError(Exception):
    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


def strict_schema(schema):
    """Require every object key while preserving optional values as null."""
    def visit(node):
        if not isinstance(node, dict):
            return
        node.pop("default", None)
        properties = node.get("properties")
        if properties is not None:
            required = set(node.get("required", ()))
            for name, child in properties.items():
                visit(child)
                if name not in required and child.get("type") != "null" and not any(
                    branch.get("type") == "null" for branch in child.get("anyOf", ())
                ):
                    properties[name] = {"anyOf": [child, {"type": "null"}]}
            node["required"] = list(properties)
            node["additionalProperties"] = False
        for child in node.get("$defs", {}).values():
            visit(child)
        for child in node.get("anyOf", ()):
            visit(child)
        visit(node.get("items"))

    result = deepcopy(schema)
    visit(result)
    return result


def _restore_defaults(data, schema, root):
    if "$ref" in schema:
        schema = root["$defs"][schema["$ref"].rsplit("/", 1)[-1]]
    if "anyOf" in schema and data is not None:
        for branch in schema["anyOf"]:
            if branch.get("type") != "null":
                return _restore_defaults(data, branch, root)
    if isinstance(data, list) and "items" in schema:
        return [_restore_defaults(item, schema["items"], root) for item in data]
    if isinstance(data, dict):
        properties = schema.get("properties", {})
        return {
            name: _restore_defaults(value, properties.get(name, {}), root)
            for name, value in data.items()
            if not (value is None and name in properties and name not in schema.get("required", ())
                    and not any(part.get("type") == "null" for part in properties[name].get("anyOf", ())))
        }
    return data


def _safe(message, key):
    message = str(message)
    if key:
        message = message.replace(key, "[REDACTED]")
    return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", message)


def _openai(key, model, system, user, schema, temperature, usage):
    payload = {
        "model": model, "instructions": system, "input": user, "store": False,
        "text": {"format": {"type": "json_schema", "name": "result",
                           "strict": True, "schema": strict_schema(schema)}},
    }
    if temperature is not None:
        payload["temperature"] = temperature
    response = httpx.post("https://api.openai.com/v1/responses", json=payload,
                          headers={"Authorization": f"Bearer {key}"}, timeout=config.GEMINI_TIMEOUT_MS / 1000)
    if response.is_error:
        try:
            error = response.json().get("error") or {}
        except ValueError:
            error = {}
        raise LLMError(error.get("code") or f"HTTP_{response.status_code}",
                       _safe(error.get("message") or response.reason_phrase, key), response.status_code)
    result = response.json()
    metering = result.get("usage") or {}
    usage.update(input_tokens=metering.get("input_tokens"), output_tokens=metering.get("output_tokens"))
    for item in result.get("output", ()):
        for part in item.get("content", ()):
            if part.get("type") == "output_text" and result.get("status") == "completed":
                return json.dumps(_restore_defaults(json.loads(part["text"]), schema, schema), ensure_ascii=False)
            if part.get("type") == "refusal":
                raise LLMError("REFUSAL", _safe(part.get("refusal", ""), key))
    raise LLMError("INCOMPLETE_RESPONSE", _safe(result.get("incomplete_details") or result.get("status"), key))


def _gemini(key, model, system, user, schema, temperature, usage):
    try:
        with genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(
            timeout=config.GEMINI_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)
        )) as client:
            response = client.models.generate_content(
                model=model, contents=user,
                config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                    response_json_schema=schema, temperature=temperature,
                    thinking_config=types.ThinkingConfig(thinking_level="medium")),
            )
    except errors.APIError as exc:
        raise LLMError(f"HTTP_{exc.code}", _safe(exc.message, key), exc.code) from None
    metering = getattr(response, "usage_metadata", None)
    usage.update(input_tokens=getattr(metering, "prompt_token_count", None),
                 output_tokens=getattr(metering, "candidates_token_count", None))
    return response.text or ""


_INVISIBLE = re.compile(r"[\uFEFF\u200B-\u200D\u2060]")


def clean_json(raw):
    def clean(value):
        if isinstance(value, str):
            return _INVISIBLE.sub("", value)
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {clean(key): clean(item) for key, item in value.items()}
        return value

    try:
        parsed = json.loads(raw.lstrip("\ufeff"))
    except ValueError:
        return _INVISIBLE.sub("", raw)
    return json.dumps(clean(parsed), ensure_ascii=False)


def generate_json(system, user, schema, temperature, task):
    provider = config.LLM_PROVIDER
    if provider not in ("openai", "gemini"):
        raise LLMError("INVALID_PROVIDER", "LLM_PROVIDER는 openai 또는 gemini여야 합니다.")
    is_openai = provider == "openai"
    key = (config.OPENAI_API_KEY if is_openai else config.GEMINI_API_KEY).strip()
    model = config.OPENAI_MODEL if is_openai else config.GEMINI_MODEL
    generate = _openai if is_openai else _gemini
    delays = iter(OVERLOAD_DELAYS)
    if is_openai and temperature is not None and model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
        temperature = None
        logger.info("Omitting temperature for %s", model)
    attempt = 0
    while True:
        attempt += 1
        start = perf_counter()
        usage = dict(input_tokens=None, output_tokens=None)
        code = "ok"
        temperature_sent = temperature is not None
        try:
            if not key:
                raise LLMError("KEY_MISSING", "서비스 연결 설정을 확인해 주세요.")
            return clean_json(generate(key, model, system, user, schema, temperature, usage))
        except LLMError as exc:
            code = exc.code
            if (is_openai and temperature is not None and exc.status == 400
                    and "temperature" in str(exc).lower()
                    and exc.code in ("unsupported_parameter", "unsupported_value")):
                temperature = None
                logger.info("Omitting unsupported temperature for %s", model)
                continue
            retryable = exc.code != "insufficient_quota" and (
                (exc.status is not None and 500 <= exc.status < 600)
                or (is_openai and exc.status == 429)
            )
            delay = next(delays, None) if retryable else None
            if delay is None:
                raise
        except Exception as exc:
            code = type(exc).__name__
            raise LLMError(code, _safe(str(exc), key)) from None
        finally:
            log = LOG_PATH
            log.parent.mkdir(exist_ok=True)
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(dict(timestamp=datetime.now(timezone.utc).isoformat(),
                    task=task, provider=provider, model=model, attempt=attempt,
                    duration_ms=round((perf_counter() - start) * 1000), code=code,
                    temperature_sent=temperature_sent, **usage)) + "\n")
        sleep(delay)
