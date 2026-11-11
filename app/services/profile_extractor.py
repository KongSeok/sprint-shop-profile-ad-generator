import json
from typing import Literal

from pydantic import ValidationError

from app.services.llm_client import LLMError, QUOTA_MESSAGE, generate_json
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
    try:
        raw_text = generate_json(prompt, text, ShopProfile.model_json_schema(), 0.1, "profile_extract")
    except LLMError as exc:
        if exc.code == "insufficient_quota":
            raise ProfileExtractionError("LLM_QUOTA_EXHAUSTED", QUOTA_MESSAGE, 503, exc.status) from exc
        if exc.code == "KEY_MISSING":
            raise ProfileExtractionError("GEMINI_KEY_MISSING", str(exc)) from exc
        raise ProfileExtractionError("GEMINI_CALL_FAILED", f"{exc.code}: {exc}", 502, exc.status) from exc
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
