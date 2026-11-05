import json

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.services.fact_check import fact_warnings, output_text, merge_warnings
from app.services.style_check import style_warnings
from app.services.copy_examples import select_examples, example_warnings
from app.core import config
from app.schemas.copy import CopyGenerateResponse, CopyMenu, GeneratedCopy, generated_copy_model
from app.schemas.concept import Concept, can_suggest
from app.schemas.profile import ShopProfile


class CopyGenerationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502, upstream_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.upstream_status = upstream_status


def build_copy_prompt(profile: ShopProfile, menu: CopyMenu, prompt_version: str = "v2", *, concept: Concept | None = None, use_examples: bool = True, example_version: str = "full-v3", example_seed: int | None = None) -> tuple[str, str]:
    return prepare_copy_prompt(profile, menu, prompt_version, concept=concept, use_examples=use_examples, example_version=example_version, example_seed=example_seed)[:2]


def prepare_copy_prompt(profile, menu, prompt_version="v2", *, concept=None, use_examples=True, example_version="full-v3", example_seed=None, mode=None):
    if example_version not in ("short-v1", "full-v2", "full-v3"):
        raise CopyGenerationError("INVALID_EXAMPLE_VERSION", "예시 버전을 확인해 주세요", 422)
    if prompt_version not in ("v1", "v2"):
        raise CopyGenerationError("INVALID_PROMPT_VERSION", "prompt_version은 v1 또는 v2여야 합니다", 422)
    try:
        prompt = (config.PROJECT_ROOT / f"app/prompts/copy_{prompt_version}.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CopyGenerationError("COPY_PROMPT_NOT_READY", "문구 생성 준비를 확인해 주세요", 503) from exc
    contents = json.dumps({
        "profile": profile.model_dump(mode="json", exclude_none=True),
        **({"menu": menu.model_dump(mode="json", exclude_none=True)} if menu is not None else {}),
    }, ensure_ascii=False)
    if concept is not None and can_suggest(profile):
        selected = Concept.model_validate(concept)
        data = json.loads(contents)
        data['concept'] = {'mood': selected.mood, 'tone': selected.tone}
        contents = json.dumps(data, ensure_ascii=False)
        prompt += "\nconcept는 사장님이 고른 컨셉. 사실이 아니니 사실처럼 쓰지 않기. concept.tone을 말투로, concept.mood를 분위기 참고로만 사용한다. 컨셉에서 숫자·원산지·품질 등의 사실을 가져오지 않는다."
    examples = select_examples(config.PROJECT_ROOT / "data/copy_examples/examples.jsonl", profile.business_type, seed=example_seed, example_version=example_version, mode=mode) if prompt_version == "v2" and use_examples else []
    if examples:
        if mode == 'shop':
            # Reuse Place prose as shop-intro examples; no menu-description examples.
            examples = [r for r in examples if r['channel'] != 'delivery_app']
        grouped = {channel: [r["text"] for r in examples if r["channel"] == channel] for channel in ("instagram", "delivery_app", "naver_place")}
        if example_version in ("full-v2", "full-v3"):
            grouped["instagram"] = {
                "흐름·말투 참고 (문장 그대로 쓰지 말 것)": [r["text"] for r in examples if r["channel"] == "instagram" and r.get("kind") == "full"],
                "짧은 표현 참고": [r["text"] for r in examples if r["channel"] == "instagram" and r.get("kind") == "short"],
            }
        if example_version == "full-v3":
            grouped["instagram"] = {
                "통 글 예시": [r["text"] for r in examples if r["channel"] == "instagram" and r.get("kind") == "full"],
                "짧은 표현 예시": [r["text"] for r in examples if r["channel"] == "instagram" and r.get("kind") == "short"],
            }
            prompt += "\n아래 예시는 말투와 흐름만 참고하고, 문장·구조·단어는 따라 하지 마세요."
        if mode == 'shop':
            grouped['delivery_app.shop_intro'] = grouped.pop('naver_place')
            grouped['naver_place'] = grouped['delivery_app.shop_intro']
            grouped.pop('delivery_app', None)
        if mode == 'menu':
            grouped['delivery_app.menu_description'] = grouped.pop('delivery_app')
            grouped.pop('naver_place', None)
            examples = [r for r in examples if r['channel'] != 'naver_place']
        prompt += "\n채널별 말투 예시:\n" + json.dumps(grouped, ensure_ascii=False)
    return prompt, contents, examples


def banned_expression_warnings(profile: ShopProfile, generated: GeneratedCopy) -> list[str]:
    texts = [generated.instagram.body, *generated.instagram.hashtags,
             generated.delivery_app.body, generated.naver_place.body]
    return [f"피할 표현 '{word}'이 들어갔어요" for word in dict.fromkeys(profile.avoid_expressions or [])
            if word and any(word in text for text in texts)]


def below_minimum_warning(errors: list[dict]) -> str | None:
    labels = {'delivery_app': '배달앱', 'naver_place': '네이버 플레이스'}
    short = [labels[error['loc'][0]] for error in errors
             if error['type'] == 'string_too_short' and error['loc']
             and error['loc'][0] in labels]
    if short:
        return '글자 수 하한 미달: ' + ', '.join(dict.fromkeys(short))
    return None


def generate_copy(profile: ShopProfile, menu: CopyMenu, prompt_version: str = "v2", *, concept: Concept | None = None, use_examples: bool = True, example_version: str = "full-v3", example_seed: int | None = None, mode: str | None = None) -> CopyGenerateResponse:
    if mode is not None:
        from app.services.copy_pipeline import generate_mode_copy
        return generate_mode_copy(profile, menu, prompt_version, mode=mode, concept=concept,
                                  use_examples=use_examples, example_version=example_version, example_seed=example_seed)
    prompt, contents, examples = prepare_copy_prompt(profile, menu, prompt_version, concept=concept, use_examples=use_examples, example_version=example_version, example_seed=example_seed)
    response_model = generated_copy_model(prompt_version)
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
                    response_json_schema=response_model.model_json_schema(),
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
        generated = response_model.model_validate_json(response.text or "")
    except ValidationError as exc:
        warning = below_minimum_warning(exc.errors(include_input=False)) if prompt_version == 'v2' else None
        if warning:
            raise CopyGenerationError('COPY_LENGTH_BELOW_MIN', warning + '. 다시 눌러 주세요') from exc
        raise CopyGenerationError("COPY_VALIDATION_FAILED", "문구 응답의 형식을 확인하지 못했어요. 다시 눌러 주세요") from exc
    factual_inputs = json.dumps({"profile": profile.model_dump(mode="json", exclude_none=True), "menu": menu.model_dump(mode="json", exclude_none=True)}, ensure_ascii=False)
    warnings = banned_expression_warnings(profile, generated)
    if prompt_version == "v2" and use_examples:
        if not examples:
            warnings.append("문구 예시 파일이 없거나 비어 있어 예시 없이 만들었어요")
        warnings.extend(example_warnings(examples, factual_inputs, generated.model_dump_json()))
    warnings.extend(fact_warnings(factual_inputs, output_text(generated)))
    if prompt_version == 'v2':
        warnings.extend(style_warnings(generated))
    return CopyGenerateResponse(**generated.model_dump(), warnings=merge_warnings(warnings), example_ids=[str(row["id"]) for row in examples])
