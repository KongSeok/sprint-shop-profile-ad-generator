import json
from typing import Literal

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.core import config
from app.schemas.profile import ShopProfile
from app.services.fewshot_loader import FewShotError, load_fewshot_examples


class ProfileExtractionError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 503,
                 upstream_status: int | None = None, raw_text: str | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.upstream_status = upstream_status
        self.raw_text = raw_text


def build_prompt(prompt_version: Literal["v1", "v2"]) -> str:
    if prompt_version not in ("v1", "v2"):
        raise ProfileExtractionError("INVALID_PROMPT_VERSION", "prompt_version은 v1 또는 v2여야 합니다.", 422)
    path = config.PROJECT_ROOT / "app" / "prompts" / f"profile_{prompt_version}.txt"
    try:
        prompt = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProfileExtractionError("PROMPT_NOT_READY", f"{path.name} 프롬프트 파일을 확인해 주세요.") from exc
    if prompt_version == "v2":
        try:
            examples = load_fewshot_examples()
        except FewShotError as exc:
            raise ProfileExtractionError("FEWSHOT_NOT_READY", str(exc)) from exc
        prompt = prompt.replace("{{few_shot_examples}}", json.dumps(examples, ensure_ascii=False))
    return prompt


def extract_profile(text: str, prompt_version: Literal["v1", "v2"] = "v2") -> ShopProfile:
    return extract_profile_raw(text, prompt_version)[1]


def extract_profile_raw(
    text: str, prompt_version: Literal["v1", "v2"] = "v2", *,
    system_prompt: str | None = None,
) -> tuple[str, ShopProfile]:
    # Validate prompt data before creating a client, especially for incomplete v2.
    prompt = system_prompt if system_prompt is not None else build_prompt(prompt_version)
    api_key = config.GEMINI_API_KEY.strip()
    if not api_key:
        raise ProfileExtractionError("GEMINI_KEY_MISSING", "GEMINI_API_KEY가 없습니다. .env 또는 환경변수를 설정해 주세요.")
    try:
        with genai.Client(
            api_key=api_key,
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=30_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        ) as client:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=text,
                config=types.GenerateContentConfig(
                    system_instruction=prompt,
                    response_mime_type="application/json",
                    response_schema=ShopProfile,
                    temperature=0.1,
                ),
            )
    except errors.APIError as exc:
        # SDK messages may contain request metadata. Never echo the key.
        reason = str(exc.message or "응답 오류").replace(api_key, "[REDACTED]")[:500]
        raise ProfileExtractionError(
            "GEMINI_CALL_FAILED",
            f"Gemini 호출 실패 (HTTP {exc.code}): {reason}",
            502,
            upstream_status=exc.code,
        ) from exc
    except Exception as exc:
        raise ProfileExtractionError(
            "GEMINI_CALL_FAILED",
            f"Gemini 호출 실패 ({type(exc).__name__}). 네트워크와 SDK 설정을 확인해 주세요.",
            502,
        ) from exc
    raw_text = response.text
    if not raw_text:
        raise ProfileExtractionError("GEMINI_EMPTY_RESPONSE", "Gemini가 프로필 JSON을 반환하지 않았습니다. 차단 여부나 응답 종료 상태를 확인해 주세요.", 502, raw_text=raw_text)
    try:
        return raw_text, ShopProfile.model_validate_json(raw_text)
    except ValidationError as exc:
        fields = ", ".join(
            f"{'.'.join(map(str, error['loc'])) or 'JSON'}: {error['type']}"
            for error in exc.errors()
        )
        raise ProfileExtractionError(
            "PROFILE_VALIDATION_FAILED", f"Gemini 응답의 프로필 스키마 검증 실패: {fields}",
            502, raw_text=raw_text,
        ) from exc
