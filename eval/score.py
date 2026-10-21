"""Offline deterministic fact scoring. This module never imports an LLM SDK."""

import argparse
import csv
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.schemas.profile import ShopProfile
from eval.common import ROOT, check_run_name, load_eval_ids, read_json, read_rows, utc_now

MATCH_DICE_THRESHOLD = 0.5
SOURCE_BIGRAM_THRESHOLD = 0.6
STRING_FIELDS = (
    "shop_name", "business_type", "location", "hours", "closed_days",
    "takeout_delivery", "parking", "tone",
)
LIST_FIELDS = ("avoid_expressions", "owner_phrases", "other_info")
STRICT_FIELDS = {"shop_name", "business_type", "menus.name", "avoid_expressions", "owner_phrases"}
RECALL_FIELDS = (*STRING_FIELDS, "mood_strengths", "menus", *LIST_FIELDS)
FACT_COLUMNS = ("id", "field", "gold_value", "pred_value", "score", "result")
ID_COLUMNS = ("id", "gold_facts", "hit", "recall", "pred_facts", "extra", "invented", "conflict_hit", "conflict_false")
SUMMARY_COLUMNS = (
    "run_name", "prompt_version", "model", "prompt_sha1", "scored_at", "n_scored", "n_missing",
    "recall_micro", "recall_macro", "invented_total", "invented_per_id", "extra_total",
    "conflict_hit_rate", *(f"recall_{field}" for field in RECALL_FIELDS),
)


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).lower()
    return "".join(char for char in text if not char.isspace() and unicodedata.category(char)[0] not in "PS")


def numbers(value: str) -> list[str]:
    # Digit runs, in original order; thousands separators are removed first.
    return re.findall(r"\d+", unicodedata.normalize("NFKC", value).replace(",", ""))


def bigrams(value: str) -> set[str]:
    text = normalize(value)
    if len(text) < 2:
        return {text} if text else set()
    return {text[index:index + 2] for index in range(len(text) - 1)}


def dice(left: str, right: str) -> float:
    first, second = bigrams(left), bigrams(right)
    return 2 * len(first & second) / (len(first) + len(second)) if first or second else 0.0


def contains_numbers(required: str, actual: str) -> bool:
    return not (Counter(numbers(required)) - Counter(numbers(actual)))


@dataclass(frozen=True)
class Fact:
    field: str
    value: str
    menu_index: int | None = None


def split_facts(profile: dict) -> list[Fact]:
    facts = []
    for field in STRING_FIELDS:
        if profile.get(field) and normalize(profile[field]):
            facts.append(Fact(field, profile[field]))
    for value in re.split(r"[,，]", profile.get("mood_strengths") or ""):
        if normalize(value):
            facts.append(Fact("mood_strengths", value.strip()))
    for index, menu in enumerate(profile.get("menus") or []):
        if normalize(menu["name"]):
            facts.append(Fact("menus.name", menu["name"], index))
        if menu.get("price") is not None and normalize(menu["price"]):
            facts.append(Fact("menus.price", menu["price"], index))
    for field in LIST_FIELDS:
        for value in profile.get(field) or []:
            if normalize(value):
                facts.append(Fact(field, value))
    return facts


def match_score(gold: Fact, pred: Fact) -> tuple[bool, float]:
    if gold.field != pred.field:
        return False, 0.0
    if gold.field == "menus.price":
        exact = numbers(gold.value) == numbers(pred.value)
        return exact, float(exact)
    if gold.field in STRICT_FIELDS:
        first, second = normalize(gold.value), normalize(pred.value)
        if first == second:
            return True, 1.0
        if gold.field == "menus.name" and first and second and (first in second or second in first):
            return True, dice(gold.value, pred.value)
        return False, 0.0
    overlap = dice(gold.value, pred.value)
    return overlap >= MATCH_DICE_THRESHOLD and contains_numbers(gold.value, pred.value), overlap


def source_evidence(fact: Fact, text: str) -> tuple[bool, float]:
    if fact.field in STRICT_FIELDS or fact.field == "menus.price":
        supported = normalize(fact.value) in normalize(text)
        return supported, float(supported)
    pieces = bigrams(fact.value)
    overlap = len(pieces & bigrams(text)) / len(pieces) if pieces else 0.0
    return contains_numbers(fact.value, text) and overlap >= SOURCE_BIGRAM_THRESHOLD, overlap


def score_profile(row_id: int, gold: dict, pred: dict, text: str) -> tuple[list[dict], dict]:
    gold_facts, pred_facts = split_facts(gold), split_facts(pred)
    matched_gold, matched_pred = set(), set()
    pairs = []
    # Greedy one-to-one matching, strongest similarity first; deterministic ties.
    candidates = []
    for gi, expected in enumerate(gold_facts):
        if expected.field == "menus.price":
            continue
        for pi, actual in enumerate(pred_facts):
            accepted, similarity = match_score(expected, actual)
            if accepted:
                candidates.append((-similarity, gi, pi))
    for negative_score, gi, pi in sorted(candidates):
        if gi not in matched_gold and pi not in matched_pred:
            matched_gold.add(gi)
            matched_pred.add(pi)
            pairs.append((gi, pi, -negative_score))
    # A price can hit only within a matched menu-name pair.
    for gi, pi, _ in list(pairs):
        if gold_facts[gi].field != "menus.name":
            continue
        gold_price = next((i for i, fact in enumerate(gold_facts)
                           if fact.field == "menus.price" and fact.menu_index == gold_facts[gi].menu_index), None)
        pred_price = next((i for i, fact in enumerate(pred_facts)
                           if fact.field == "menus.price" and fact.menu_index == pred_facts[pi].menu_index), None)
        if gold_price is not None and pred_price is not None:
            accepted, similarity = match_score(gold_facts[gold_price], pred_facts[pred_price])
            if accepted:
                matched_gold.add(gold_price)
                matched_pred.add(pred_price)
                pairs.append((gold_price, pred_price, similarity))
    rows = []
    for gi, pi, similarity in sorted(pairs):
        rows.append(dict(id=row_id, field=gold_facts[gi].field, gold_value=gold_facts[gi].value,
                         pred_value=pred_facts[pi].value, score=similarity, result="hit"))
    for gi, fact in enumerate(gold_facts):
        if gi not in matched_gold:
            rows.append(dict(id=row_id, field=fact.field, gold_value=fact.value,
                             pred_value="", score=0.0, result="miss"))
    for pi, fact in enumerate(pred_facts):
        if pi not in matched_pred:
            supported, overlap = source_evidence(fact, text)
            rows.append(dict(id=row_id, field=fact.field, gold_value="", pred_value=fact.value,
                             score=overlap, result="extra" if supported else "invented"))
    counts = Counter(row["result"] for row in rows)
    metrics = dict(
        id=row_id, gold_facts=len(gold_facts), hit=len(matched_gold),
        recall=len(matched_gold) / len(gold_facts) if gold_facts else 1.0,
        pred_facts=len(pred_facts), extra=counts["extra"], invented=counts["invented"],
        conflict_hit=int(bool(gold.get("needs_check")) and bool(pred.get("needs_check"))),
        conflict_false=int(not gold.get("needs_check") and bool(pred.get("needs_check"))),
    )
    return rows, metrics


def write_csv(path: Path, columns, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def score_run(run_name: str, allow_missing: bool = False, *, root: Path = ROOT) -> dict:
    check_run_name(run_name)
    targets = load_eval_ids(root)
    gold_rows = read_rows(root / "data/samples/answer_profiles_gold.jsonl")
    texts = read_rows(root / "data/samples/shop_texts.jsonl")
    loaded, missing, metadata = {}, [], set()
    gold_profiles = {}
    for row_id in targets:
        if row_id not in gold_rows or row_id not in texts or not isinstance(texts[row_id].get("text"), str):
            raise ValueError(f"ID {row_id}: 정답 또는 원문이 없습니다.")
        try:
            gold_profiles[row_id] = ShopProfile.model_validate(gold_rows[row_id].get("profile")).model_dump()
        except ValidationError as exc:
            raise ValueError(f"ID {row_id}: 정답 프로필 스키마 오류") from exc
        if run_name == "gold":
            loaded[row_id] = gold_profiles[row_id]
            continue
        path = root / "experiments/runs" / run_name / f"{row_id}.json"
        if not path.exists():
            missing.append(row_id)
            continue
        record = read_json(path)
        if not isinstance(record, dict) or record.get("id") != row_id:
            raise ValueError(f"{path.name}: 저장된 ID가 파일명과 다릅니다.")
        if not isinstance(record.get("profile"), dict):
            missing.append(row_id)
            continue
        try:
            loaded[row_id] = ShopProfile.model_validate(record["profile"]).model_dump()
        except ValidationError as exc:
            raise ValueError(f"{path.name}: 저장된 예측 프로필 스키마 오류") from exc
        meta = tuple(record.get(key, "") for key in ("prompt_version", "model", "prompt_sha1"))
        if not all(isinstance(value, str) and value for value in meta):
            raise ValueError(f"{path.name}: prompt_version/model/prompt_sha1 메타데이터가 없습니다.")
        metadata.add(meta)
    if missing and not allow_missing:
        raise ValueError(f"profile 없는 eval ID: {missing}. --allow-missing으로 해당 ID를 빼고 채점할 수 있습니다.")
    if len(metadata) > 1:
        raise ValueError("실행 폴더에 서로 다른 prompt_version/model/prompt_sha1이 섞여 있습니다. run-name을 분리하세요.")
    all_facts, by_id = [], []
    for row_id, pred in loaded.items():
        rows, metrics = score_profile(row_id, gold_profiles[row_id], pred, texts[row_id]["text"])
        all_facts.extend(rows)
        by_id.append(metrics)
    total_gold = sum(row["gold_facts"] for row in by_id)
    total_hit = sum(row["hit"] for row in by_id)
    conflict_gold = sum(bool(gold_profiles[row_id].get("needs_check")) for row_id in loaded)
    version, model, sha1 = next(iter(metadata)) if metadata else (("gold", "gold", "") if run_name == "gold" else ("", "", ""))
    summary = dict(
        run_name=run_name, prompt_version=version, model=model, prompt_sha1=sha1, scored_at=utc_now(),
        n_scored=len(by_id), n_missing=len(missing),
        recall_micro=(total_hit / total_gold if total_gold else 1.0) if by_id else "",
        recall_macro=sum(row["recall"] for row in by_id) / len(by_id) if by_id else "",
        invented_total=sum(row["invented"] for row in by_id),
        invented_per_id=sum(row["invented"] for row in by_id) / len(by_id) if by_id else "",
        extra_total=sum(row["extra"] for row in by_id),
        conflict_hit_rate=sum(row["conflict_hit"] for row in by_id) / conflict_gold if conflict_gold else "",
    )
    field_totals = defaultdict(Counter)
    for row in all_facts:
        field_totals[row["field"].split(".")[0]][row["result"]] += 1
    for field in RECALL_FIELDS:
        count = field_totals[field]
        denominator = count["hit"] + count["miss"]
        summary[f"recall_{field}"] = count["hit"] / denominator if denominator else ""
    output_dir = root / "eval/results"
    summary_path = output_dir / "summary.csv"
    previous = []
    if summary_path.exists():
        with summary_path.open(encoding="utf-8-sig", newline="") as stream:
            previous = [row for row in csv.DictReader(stream) if row["run_name"] != run_name]
    write_csv(output_dir / f"{run_name}_facts.csv", FACT_COLUMNS, all_facts)
    write_csv(output_dir / f"{run_name}_by_id.csv", ID_COLUMNS, by_id)
    write_csv(summary_path, SUMMARY_COLUMNS, [*previous, summary])
    print(f"{run_name}: 채점 {len(by_id)} / 누락 {len(missing)}")
    print(f"recall micro={summary['recall_micro']}, macro={summary['recall_macro']}")
    print(f"invented={summary['invented_total']}, extra={summary['extra_total']}, conflict_hit_rate={summary['conflict_hit_rate']}")
    print(f"결과: {summary_path}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args(argv)
    try:
        score_run(args.run_name, args.allow_missing)
    except ValueError as exc:
        print(f"채점 중단: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
