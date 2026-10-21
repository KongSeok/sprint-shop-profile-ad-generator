"""File helpers shared by both CLIs; no provider SDK imports."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_run_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("run-name은 영문·숫자로 시작하고 영문·숫자·밑줄·하이픈·점만 사용하세요.")
    return name


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name} 파일을 읽을 수 없습니다: {type(exc).__name__}") from exc


def read_rows(path: Path) -> dict[int, dict]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"{path.name} 파일을 UTF-8로 준비해 주세요.") from exc
    rows = {}
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} {number}줄: JSON 형식 오류") from exc
        if not isinstance(row, dict) or type(row.get("id")) is not int:
            raise ValueError(f"{path.name} {number}줄: 정수 id가 필요합니다.")
        if row["id"] in rows:
            raise ValueError(f"{path.name}: 중복 ID {row['id']}")
        rows[row["id"]] = row
    return rows


def load_eval_ids(root: Path) -> list[int]:
    split = read_json(root / "data/samples/split.json")
    if not isinstance(split, dict):
        raise ValueError("split.json은 train/eval 목록을 가진 객체여야 합니다.")
    for group in ("train", "eval"):
        ids = split.get(group)
        if not isinstance(ids, list) or any(type(value) is not int for value in ids):
            raise ValueError(f"split.json의 {group}은 정수 ID 목록이어야 합니다.")
        if len(ids) != len(set(ids)):
            raise ValueError(f"split.json의 {group}에 중복 ID가 있습니다.")
    if set(split["train"]) & set(split["eval"]):
        raise ValueError("train과 eval ID가 겹칩니다.")
    if not split["eval"]:
        raise ValueError("eval ID가 비어 있습니다.")
    return split["eval"]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
