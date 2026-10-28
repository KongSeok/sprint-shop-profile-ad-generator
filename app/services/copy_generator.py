import json

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.services.copy_examples import select_examples, example_warnings
from app.core import config
from app.schemas.copy import CopyGenerateResponse, CopyMenu, GeneratedCopy
from app.schemas.profile import ShopProfile


class CopyGenerationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502, upstream_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.upstream_status = upstream_status


def build_copy_prompt(profile: ShopProfile, menu: CopyMenu, prompt_version: str = "v2") -> tuple[str, str]:
    return prepare_copy_prompt(profile, menu, prompt_version)[:2]


def prepare_copy_prompt(profile, menu, prompt_version="v2"):
    if prompt_version not in ("v1", "v2"):
        raise CopyGenerationError("INVALID_PROMPT_VERSION", "prompt_version은 v1 또는 v2여야 합니다", 422)
    try:
        prompt = (config.PROJECT_ROOT / f"app/prompts/copy_{prompt_version}.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CopyGenerationError("COPY_PROMPT_NOT_READY", "문구 생성 준비를 확인해 주세요", 503) from exc
    contents = json.dumps({
        "profile": profile.model_dump(mode="json", exclude_none=True),
        "menu": menu.model_dump(mode="json", exclude_none=True),
    }, ensure_ascii=False)
    examples = select_examples(config.PROJECT_ROOT / "data/copy_examples/examples.jsonl", profile.business_type) if prompt_version == "v2" else []
    if examples:
        prompt += "\n채널별 말투 예시:\n" + json.dumps({channel: [r["text"] for r in examples if r["channel"] == channel] for channel in ("instagram", "delivery_app", "naver_place")}, ensure_ascii=False)
    return prompt, contents, examples


def banned_expression_warnings(profile: ShopProfile, generated: GeneratedCopy) -> list[str]:
    texts = [generated.instagram.body, *generated.instagram.hashtags,
             generated.delivery_app.body, generated.naver_place.body]
    return [f"피할 표현 '{word}'이 들어갔어요" for word in dict.fromkeys(profile.avoid_expressions or [])
            if word and any(word in text for text in texts)]


def generate_copy(profile: ShopProfile, menu: CopyMenu, prompt_version: str = "v2") -> CopyGenerateResponse:
    prompt, contents, examples = prepare_copy_prompt(profile, menu, prompt_version)
    api_key = config.GEMINI_API_KEY.strip()
    if not api_key:
        raise CopyGenerationError("GEMINI_KEY_MISSING", "서비스 연결 설정을 확인해 주세요", 503)
    try:
        with genai.Client(
            api_key=api_key, vertexai=False,
            http_options=types.HttpOptions(timeout=config.GEMINI_TIMEOUT_MS,
                                           retry_options=types.HttpRetryOptions(attempts=1)),
        ) as client:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL, contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=prompt, response_mime_type="application/json",
                    response_json_schema=GeneratedCopy.model_json_schema(),
                    temperature=0.7, thinking_config=types.ThinkingConfig(thinking_level="medium"),
                ),
            )
    except errors.APIError as exc:
        if exc.code in (429, 503, 504):
            raise CopyGenerationError("COPY_RETRY_LATER", "잠시 후 다시 눌러 주세요", 503, exc.code) from exc
        reason = str(exc.message or "응답 오류").replace(api_key, "[REDACTED]")[:500]
        raise CopyGenerationError("COPY_CALL_FAILED", f"Gemini 호출 실패 (HTTP {exc.code}): {reason}", 502, exc.code) from exc
    except Exception as exc:
        raise CopyGenerationError("COPY_CALL_FAILED", f"문구 생성 연결 실패 ({type(exc).__name__})") from exc
    try:
        generated = GeneratedCopy.model_validate_json(response.text or "")
    except ValidationError as exc:
        raise CopyGenerationError("COPY_VALIDATION_FAILED", "문구 응답의 형식을 확인하지 못했어요. 다시 눌러 주세요") from exc
    warnings = banned_expression_warnings(profile, generated)
    if prompt_version == "v2":
        if not examples:
            warnings.append("문구 예시 파일이 없거나 비어 있어 예시 없이 만들었어요")
        warnings.extend(example_warnings(examples, contents, generated.model_dump_json()))
    return CopyGenerateResponse(**generated.model_dump(), warnings=list(dict.fromkeys(warnings)), example_ids=[str(row["id"]) for row in examples])
