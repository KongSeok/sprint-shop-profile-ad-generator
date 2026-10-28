import json
from google import genai
from google.genai import errors, types
from pydantic import ValidationError
from app.core import config
from app.schemas.concept import ConceptSuggestions, allowed_themes, can_suggest


class ConceptSuggestionError(Exception):
    def __init__(self, code, message, status_code=502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def suggest_concepts(profile):
    if not can_suggest(profile):
        raise ConceptSuggestionError('CONCEPT_ALREADY_SET', '이미 분위기·말투가 있어요', 409)
    api_key = config.GEMINI_API_KEY.strip()
    if not api_key:
        raise ConceptSuggestionError('GEMINI_KEY_MISSING', '서비스 연결 설정을 확인해 주세요', 503)
    try:
        prompt = (config.PROJECT_ROOT / 'app/prompts/concept_v1.txt').read_text(encoding='utf-8')
        prompt += '\n허용 테마: ' + json.dumps(allowed_themes(), ensure_ascii=False)
        contents = json.dumps(profile.model_dump(mode='json', include={'shop_name', 'business_type', 'menus'}), ensure_ascii=False)
        with genai.Client(api_key=api_key, vertexai=False, http_options=types.HttpOptions(
            timeout=config.GEMINI_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1))) as client:
            response = client.models.generate_content(model=config.GEMINI_MODEL, contents=contents,
                config=types.GenerateContentConfig(system_instruction=prompt, response_mime_type='application/json',
                    response_json_schema=ConceptSuggestions.model_json_schema(), temperature=0.9,
                    thinking_config=types.ThinkingConfig(thinking_level='medium')))
    except errors.APIError as exc:
        raise ConceptSuggestionError('CONCEPT_RETRY_LATER', '잠시 후 다시 눌러 주세요', 503 if exc.code in (429,503,504) else 502) from exc
    except (OSError, UnicodeError) as exc:
        raise ConceptSuggestionError('CONCEPT_PROMPT_NOT_READY', '컨셉 추천 준비를 확인해 주세요', 503) from exc
    except Exception as exc:
        raise ConceptSuggestionError('CONCEPT_CALL_FAILED', '컨셉을 추천하지 못했어요. 잠시 후 다시 눌러 주세요') from exc
    try:
        return ConceptSuggestions.model_validate_json(response.text or '')
    except ValidationError as exc:
        raise ConceptSuggestionError('CONCEPT_VALIDATION_FAILED', '추천 형식을 확인하지 못했어요. 잠시 후 다시 눌러 주세요') from exc
