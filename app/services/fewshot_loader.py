import json
from pathlib import Path

from pydantic import ValidationError

from app.core.config import PROJECT_ROOT
from app.schemas.profile import ShopProfile

TRAIN_IDS = (1, 7, 13, 19, 25)


class FewShotError(ValueError):
    """Few-shot 데이터를 준비하거나 수정해야 하는 오류."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise FewShotError(f"{path.name} 파일을 UTF-8 형식으로 준비해 주세요.") from exc


def _jsonl_rows(path: Path) -> list[dict]:
    content = _read_text(path)
    if not content.strip():
        raise FewShotError(f"{path.name} 파일이 비어 있습니다. train ID {TRAIN_IDS}의 데이터를 채워 주세요.")
    rows = []
    for line_number, line in enumerate(content.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FewShotError(f"{path.name} {line_number}번째 줄이 올바른 JSON이 아닙니다.") from exc
        if not isinstance(row, dict) or type(row.get("id")) is not int:
            raise FewShotError(f"{path.name} {line_number}번째 줄에는 정수 id가 필요합니다.")
        rows.append(row)
    return rows


def load_fewshot_examples(data_dir: Path | None = None) -> list[dict]:
    """split을 검증한 다음 train 원문과 수동 답안 5개만 결합한다."""
    data_dir = data_dir if data_dir is not None else PROJECT_ROOT / "data"
    answers = _jsonl_rows(data_dir / "answers" / "fewshot_profiles.jsonl")
    try:
        split = json.loads(_read_text(data_dir / "split.json"))
    except json.JSONDecodeError as exc:
        raise FewShotError("split.json은 train, eval ID 목록을 가진 JSON이어야 합니다.") from exc
    if not isinstance(split, dict):
        raise FewShotError("split.json은 train, eval ID 목록을 가진 JSON 객체여야 합니다.")
    for name in ("train", "eval"):
        ids = split.get(name)
        if not isinstance(ids, list) or any(type(value) is not int for value in ids):
            raise FewShotError(f"split.json의 {name}은 정수 ID 목록이어야 합니다.")
        if len(ids) != len(set(ids)):
            raise FewShotError(f"split.json의 {name}에 중복 ID가 있습니다.")
    if set(split["train"]) != set(TRAIN_IDS):
        raise FewShotError(f"split.json의 train ID는 정확히 {TRAIN_IDS}여야 합니다.")
    if set(split["train"]) & set(split["eval"]):
        raise FewShotError("split.json의 train과 eval ID가 겹칩니다. eval 글은 예시에 사용할 수 없습니다.")

    profiles = {}
    for row in answers:
        row_id = row["id"]
        if row_id not in TRAIN_IDS:
            raise FewShotError(f"fewshot_profiles.jsonl의 ID {row_id}는 허용된 train ID가 아닙니다.")
        if row_id in profiles:
            raise FewShotError(f"fewshot_profiles.jsonl에 ID {row_id}가 중복되었습니다.")
        try:
            profile = ShopProfile.model_validate(row.get("profile"))
        except ValidationError as exc:
            fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
            raise FewShotError(f"fewshot_profiles.jsonl의 ID {row_id} 프로필 스키마를 확인해 주세요: {fields}") from exc
        profiles[row_id] = profile.model_dump()
    if set(profiles) != set(TRAIN_IDS):
        raise FewShotError(f"fewshot_profiles.jsonl에 train ID {TRAIN_IDS}의 답안 5개가 모두 필요합니다.")

    texts = {}
    for row in _jsonl_rows(data_dir / "samples" / "shop_texts.jsonl"):
        row_id = row["id"]
        if row_id not in TRAIN_IDS:
            continue  # eval 글은 프롬프트로 가져오지 않는다.
        if row_id in texts:
            raise FewShotError(f"shop_texts.jsonl에 train ID {row_id}가 중복되었습니다.")
        text = row.get("text")
        if not isinstance(text, str) or not text.strip():
            raise FewShotError(f"shop_texts.jsonl의 ID {row_id}에 비어 있지 않은 text가 필요합니다.")
        texts[row_id] = text
    if set(texts) != set(TRAIN_IDS):
        raise FewShotError(f"shop_texts.jsonl에 train ID {TRAIN_IDS}의 원문 5개가 모두 필요합니다.")
    return [{"id": value, "text": texts[value], "profile": profiles[value]} for value in TRAIN_IDS]
