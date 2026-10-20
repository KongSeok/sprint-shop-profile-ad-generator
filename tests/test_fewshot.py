import json
from pathlib import Path

import pytest

from app.services import profile_extractor
from app.services.fewshot_loader import FewShotError, TRAIN_IDS, load_fewshot_examples


def test_loads_exact_train_ids_and_joins_by_id(fewshot_data):
    examples = load_fewshot_examples(fewshot_data)
    assert [row["id"] for row in examples] == list(TRAIN_IDS)
    assert [row["text"] for row in examples] == [f"테스트 원문 {value}" for value in TRAIN_IDS]
    assert "EVAL_MUST_NEVER_APPEAR" not in json.dumps(examples)


@pytest.mark.parametrize("split", [
    {"train": [1, 7, 13, 19, 25], "eval": [1, 2]},
    {"train": [2, 7, 13, 19, 25], "eval": [1]},
    {"train": [1, 7, 13, 19, 25, 25], "eval": [2]},
    {"train": ["1", 7, 13, 19, 25], "eval": [2]},
    {"train": [1, 7, 13, 19, 25]},
])
def test_rejects_invalid_or_leaking_split(fewshot_data, split):
    (fewshot_data / "samples" / "split.json").write_text(json.dumps(split), encoding="utf-8")
    with pytest.raises(FewShotError, match="split.json"):
        load_fewshot_examples(fewshot_data)


@pytest.mark.parametrize("problem", ["missing", "blank", "json", "duplicate", "incomplete", "schema"])
def test_rejects_unready_answers(fewshot_data, problem):
    path = fewshot_data / "samples" / "answer_profiles_gold.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if problem == "missing":
        path.unlink()
    elif problem == "blank":
        path.write_text(" \n", encoding="utf-8")
    elif problem == "json":
        path.write_text("{broken", encoding="utf-8")
    else:
        if problem == "duplicate":
            rows.append(rows[0])
        elif problem == "incomplete":
            rows = [row for row in rows if row["id"] != 1]
        else:
            rows[0]["profile"]["menus"] = [{"name": "메뉴", "price": 5000}]
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    with pytest.raises(FewShotError, match="answer_profiles_gold.jsonl"):
        load_fewshot_examples(fewshot_data)


@pytest.mark.parametrize("problem", ["missing", "duplicate", "blank"])
def test_requires_five_train_texts(fewshot_data, problem):
    path = fewshot_data / "samples" / "shop_texts.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if problem == "missing":
        rows = [row for row in rows if row["id"] != 1]
    elif problem == "duplicate":
        rows.append(rows[0])
    else:
        rows[0]["text"] = " "
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    with pytest.raises(FewShotError, match="shop_texts.jsonl"):
        load_fewshot_examples(fewshot_data)


def test_v2_prompt_contains_five_train_examples_only(fewshot_data, monkeypatch):
    monkeypatch.setattr(profile_extractor, "load_fewshot_examples", lambda: load_fewshot_examples(fewshot_data))
    prompt = profile_extractor.build_prompt("v2")
    assert "{{few_shot_examples}}" not in prompt
    assert "EVAL_MUST_NEVER_APPEAR" not in prompt
    assert "EVAL_GOLD_MUST_NEVER_APPEAR" not in prompt
    for value in TRAIN_IDS:
        assert f"테스트 원문 {value}" in prompt
    template = (Path(__file__).resolve().parents[1] / "app/prompts/profile_v2.txt").read_text(encoding="utf-8")
    prefix, suffix = template.split("{{few_shot_examples}}")
    examples_json = prompt[len(prefix):]
    if suffix:
        examples_json = examples_json[:-len(suffix)]
    assert [row["id"] for row in json.loads(examples_json)] == list(TRAIN_IDS)


def test_v1_does_not_load_examples(monkeypatch):
    def forbidden():
        raise AssertionError("v1 must not load few-shot data")
    monkeypatch.setattr(profile_extractor, "load_fewshot_examples", forbidden)
    assert "규칙:" in profile_extractor.build_prompt("v1")
