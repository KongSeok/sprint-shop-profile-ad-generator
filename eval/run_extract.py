"""Call Gemini and persist raw responses; resume without repeating successes."""

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

from app.core import config
from app.schemas.profile import ShopProfile
from pydantic import ValidationError
from app.services.profile_extractor import (
    ProfileExtractionError, build_prompt, extract_profile_raw,
)
from eval.common import ROOT, check_run_name, load_eval_ids, read_json, read_rows, utc_now, write_json

RETRY_DELAYS = (30, 60, 120)
RETRY_STATUSES = (429, 503)


def select_ids(root: Path, requested: list[int] | None) -> list[int]:
    allowed = load_eval_ids(root)
    if requested is None:
        return allowed
    invalid = sorted(set(requested) - set(allowed))
    if invalid:
        raise ValueError(f"eval ID만 호출할 수 있습니다. train 또는 잘못된 ID: {invalid}")
    return list(dict.fromkeys(requested))


def run_extract(version: str, run_name: str | None = None, ids: list[int] | None = None,
                sleep: float = 6, force: bool = False, *, root: Path = ROOT) -> dict:
    run_name = check_run_name(run_name or version)
    if run_name == "gold":
        raise ValueError("gold는 오프라인 자기검증용 이름입니다. 다른 run-name을 사용하세요.")
    if version not in ("v1", "v2") or not math.isfinite(sleep) or sleep < 0:
        raise ValueError("version은 v1/v2, sleep은 0 이상의 유한한 수여야 합니다.")
    targets = select_ids(root, ids)
    texts = read_rows(root / "data/samples/shop_texts.jsonl")
    for row_id in targets:
        if row_id not in texts or not isinstance(texts[row_id].get("text"), str) or not texts[row_id]["text"].strip():
            raise ValueError(f"shop_texts.jsonl의 ID {row_id} 원문이 없거나 비어 있습니다.")
    prompt = build_prompt(version)
    prompt_sha1 = hashlib.sha1(prompt.encode("utf-8")).hexdigest()
    model = config.GEMINI_MODEL
    run_dir = root / "experiments/runs" / run_name
    counts = {"success": 0, "failed": 0, "skipped": 0, "stopped": False}
    called = False
    for row_id in targets:
        path = run_dir / f"{row_id}.json"
        if path.exists() and not force:
            try:
                cached = read_json(path)
            except ValueError:
                cached = None
            if (isinstance(cached, dict) and cached.get("id") == row_id
                    and cached.get("model") == model and cached.get("prompt_sha1") == prompt_sha1
                    and "error" not in cached and isinstance(cached.get("profile"), dict)):
                try:
                    ShopProfile.model_validate(cached["profile"])
                except ValidationError:
                    pass  # A malformed profile is not a cached success.
                else:
                    counts["skipped"] += 1
                    continue
        if called:
            time.sleep(sleep)
        for attempt in range(len(RETRY_DELAYS) + 1):
            called = True
            record = {
                "id": row_id, "prompt_version": version, "model": model,
                "prompt_sha1": prompt_sha1, "created_at": utc_now(), "raw_text": None,
            }
            try:
                raw, profile = extract_profile_raw(texts[row_id]["text"], version, system_prompt=prompt)
                record.update(raw_text=raw, profile=profile.model_dump())
            except ProfileExtractionError as exc:
                # Do not print upstream messages or keys. Keep a redacted error on disk.
                key = config.GEMINI_API_KEY.strip()
                message = str(exc).replace(key, "[REDACTED]") if key else str(exc)
                raw = exc.raw_text
                if key and raw:
                    raw = raw.replace(key, "[REDACTED]")
                record.update(raw_text=raw, error={
                    "code": exc.code, "message": message, "upstream_status": exc.upstream_status,
                })
                write_json(path, record)
                if exc.upstream_status in RETRY_STATUSES and attempt < len(RETRY_DELAYS):
                    delay = RETRY_DELAYS[attempt]
                    print(f"ID {row_id}: Gemini HTTP {exc.upstream_status}, {delay}초 뒤 재시도 ({attempt + 1}/3)")
                    time.sleep(max(delay, sleep))
                    continue
                counts["failed"] += 1
                print(f"ID {row_id}: 실패 ({exc.code})")
                if exc.upstream_status in RETRY_STATUSES or exc.code == "GEMINI_KEY_MISSING":
                    counts["stopped"] = True
                break
            else:
                # Normally the schema contains only owner data. Redact an accidental key echo.
                key = config.GEMINI_API_KEY.strip()
                if key:
                    record = json.loads(json.dumps(record, ensure_ascii=False).replace(key, "[REDACTED]"))
                write_json(path, record)
                counts["success"] += 1
                print(f"ID {row_id}: 저장 완료")
                break
        if counts["stopped"]:
            print("지금까지의 결과는 보존했습니다. 이어서 실행하면 남은 것만 호출합니다.")
            break
    print(f"성공 {counts['success']} / 실패 {counts['failed']} / 건너뜀 {counts['skipped']}")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, choices=("v1", "v2"))
    parser.add_argument("--run-name")
    parser.add_argument("--ids", help="예: 2,3 (eval ID만 허용)")
    parser.add_argument("--sleep", type=float, default=6)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        ids = [int(value.strip()) for value in args.ids.split(",")] if args.ids is not None else None
        counts = run_extract(args.version, args.run_name, ids, args.sleep, args.force)
    except (ValueError, ProfileExtractionError) as exc:
        # Configuration/data errors do not contain raw SDK output.
        print(f"실행 중단: {exc}")
        return 1
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
