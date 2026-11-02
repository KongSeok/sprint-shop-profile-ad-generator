"""Generate resumable, manually reviewable copy samples (real network calls)."""

import argparse
import json
import time
from pathlib import Path

from pydantic import ValidationError

from app.schemas.copy import CopyMenu
from app.schemas.profile import ShopProfile
from app.services.copy_generator import CopyGenerationError, generate_copy
from eval.common import ROOT, read_rows


def run_samples(ids: list[int], *, version: str = "v1", use_examples: bool = True, features: str | None = None, this_time: str | None = None, root: Path = ROOT) -> dict:
    gold = read_rows(root / "data/samples/answer_profiles_gold.jsonl")
    suffix = "_noex" if version == "v2" and not use_examples else ""
    output_path = root / f"data/copy_runs/copy_{version}{suffix}.jsonl"
    saved = read_rows(output_path) if output_path.exists() else {}
    success = skipped = 0
    called = False
    for row_id in dict.fromkeys(ids):
        if row_id in saved:
            skipped += 1
            continue
        if row_id not in gold:
            raise ValueError(f"정답에 ID {row_id}가 없습니다")
        profile = ShopProfile.model_validate(gold[row_id].get("profile"))
        if not profile.menus:
            raise ValueError(f"ID {row_id}에 대표 메뉴가 없습니다")
        menu = CopyMenu(name=profile.menus[0].name, price=profile.menus[0].price, features=features, this_time=this_time)
        if called:
            time.sleep(6)
        called = True
        try:
            generated = generate_copy(profile, menu, version, use_examples=use_examples)
        except CopyGenerationError as exc:
            print(f"ID {row_id}: 실패 ({exc.code}). 다시 실행하면 남은 ID만 호출합니다.")
            return {"success": success, "skipped": skipped, "failed": 1}
        saved[row_id] = {"id": row_id, "prompt_version": version, "use_examples": use_examples if version == "v2" else False, "input": {"profile": profile.model_dump(), "menu": menu.model_dump()},
                         "output": generated.model_dump()}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(".tmp")
        temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in saved.values()), encoding="utf-8")
        temporary.replace(output_path)
        success += 1
        print(f"ID {row_id}: 저장 완료")
    print(f"성공 {success} / 건너뜀 {skipped}")
    return {"success": success, "skipped": skipped, "failed": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", required=True, help="예: 2,8,14,20,22")
    parser.add_argument("--version", choices=("v1", "v2"), default="v2")
    parser.add_argument("--no-examples", action="store_true")
    parser.add_argument("--features")
    parser.add_argument("--this-time")
    args = parser.parse_args(argv)
    try:
        ids = [int(value.strip()) for value in args.ids.split(",")]
        if any(value <= 0 for value in ids):
            raise ValueError("ID는 양의 정수여야 합니다")
        result = run_samples(ids, version=args.version, use_examples=not args.no_examples, features=args.features, this_time=args.this_time)
    except (ValueError, ValidationError):
        print("ID와 정답 파일의 프로필·대표 메뉴를 확인해 주세요")
        return 1
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
