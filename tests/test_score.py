import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from eval.common import ROOT, read_rows, write_json
from eval.score import dice, normalize, numbers, score_profile, score_run


def profile(**values):
    return {"shop_name": None, "business_type": None, **values}


@pytest.fixture
def score_root(tmp_path):
    shutil.copytree(ROOT / "data/samples", tmp_path / "data/samples")
    return tmp_path


def test_normalize_and_numbers():
    assert normalize(' ＡＢＣ “한 우” (등심), ·~－. ') == "abc한우등심"
    assert numbers("180g 17,000원") == ["180", "17000"]
    assert numbers("０９시 ~ １８시") == ["09", "18"]
    assert dice("주차 가능", "주차가능") == 1.0
    assert dice("가", "가") == 1.0


def test_actual_gold_25_self_check_and_summary_upsert(score_root):
    summary = score_run("gold", root=score_root)
    assert summary["n_scored"] == 25 and summary["n_missing"] == 0
    assert summary["recall_micro"] == summary["recall_macro"] == 1.0
    assert summary["invented_total"] == summary["extra_total"] == 0
    assert summary["conflict_hit_rate"] == 1.0
    output = score_root / "eval/results"
    assert (output / "gold_facts.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    score_run("gold", root=score_root)
    with (output / "summary.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 1


def test_score_import_is_independent_of_provider_sdk():
    code = "import eval.score, sys; assert 'google.genai' not in sys.modules; assert 'app.services.profile_extractor' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_different_menu_price_is_miss():
    gold = profile(menus=[{"name": "삼겹살", "price": "17,000원"}])
    pred = profile(menus=[{"name": "삼겹살", "price": "18,000원"}])
    rows, count = score_profile(2, gold, pred, "삼겹살 17,000원")
    assert count["gold_facts"] == 2 and count["hit"] == 1
    assert any(row["field"] == "menus.price" and row["result"] == "miss" for row in rows)
    assert count["invented"] == 1


def test_menu_prices_do_not_match_across_unmatched_names():
    gold = profile(menus=[{"name": "삼겹살", "price": "17,000원"}])
    pred = profile(menus=[{"name": "라떼", "price": "17,000원"}])
    _, count = score_profile(2, gold, pred, "삼겹살 17,000원")
    assert count["hit"] == 0 and count["extra"] == 1


def test_menu_containment_and_numeric_price_match():
    gold = profile(menus=[{"name": "한우 등심", "price": "180g 17,000원"}])
    pred = profile(menus=[{"name": "등심", "price": "180 g / 17000 원"}])
    assert score_profile(2, gold, pred, "")[1]["recall"] == 1.0


@pytest.mark.parametrize("gold_price,pred_price,hit", [
    ("150g 39,000원", "39,000원 (150g)", True),
    ("150g 39,000원", "39,000원 (150g, 150g)", False),
    ("무료", "무료!", True),
    ("무료", "싯가", False),
    ("39,000원", "무료", False),
])
def test_price_uses_number_counts_or_exact_text_when_numberless(gold_price, pred_price, hit):
    gold = profile(menus=[{"name": "등심", "price": gold_price}])
    pred = profile(menus=[{"name": "등심", "price": pred_price}])
    rows, _ = score_profile(2, gold, pred, "")
    assert any(row["field"] == "menus.price" and row["result"] == "hit" for row in rows) is hit


def test_reordered_unmatched_price_is_supported_by_source_numbers():
    gold = profile(menus=[{"name": "등심", "price": None}])
    pred = profile(menus=[{"name": "등심", "price": "39,000원 (150g)"}])
    rows, count = score_profile(2, gold, pred, "등심 150g 39,000원")
    assert count["extra"] == 1 and count["invented"] == 0
    assert any(row["field"] == "menus.price" and row["result"] == "extra" for row in rows)


@pytest.mark.parametrize("source,hit", [
    ("저희는 그냥 동네 빵집이고 편하게 오세요", True),
    ("저희는 그냥 동네 빵집입니다", False),
])
def test_longer_owner_phrase_requires_exact_source_excerpt(source, hit):
    gold = profile(owner_phrases=["그냥 동네 빵집"])
    pred = profile(owner_phrases=["그냥 동네 빵집이고"])
    rows, count = score_profile(2, gold, pred, source)
    assert count["hit"] == int(hit)
    if hit:
        assert count["extra"] == count["invented"] == 0
        assert rows[0]["score"] == dice("그냥 동네 빵집", "그냥 동네 빵집이고")


@pytest.mark.parametrize("prediction,expected_hit", [("동네 맛집", 1), ("지역 맛집", 0)])
def test_owner_phrases_are_normalized_exact_only(prediction, expected_hit):
    gold = profile(owner_phrases=["동네맛집"])
    pred = profile(owner_phrases=[prediction])
    assert score_profile(2, gold, pred, "동네 맛집")[1]["hit"] == expected_hit


def test_duplicate_prediction_hits_only_once_and_is_extra():
    gold = profile(other_info=["예약 가능합니다"])
    pred = profile(other_info=["예약 가능합니다", "예약 가능합니다"])
    _, count = score_profile(2, gold, pred, "예약 가능합니다")
    assert count["hit"] == 1 and count["extra"] == 1 and count["invented"] == 0
    assert count["pred_facts"] == 2


def test_one_prediction_cannot_hit_two_gold_fragments():
    gold = profile(mood_strengths="따뜻한 분위기, 따뜻한 분위기")
    assert score_profile(2, gold, profile(mood_strengths="따뜻한 분위기"), "")[1]["hit"] == 1


def test_null_gold_values_classify_source_supported_and_invented():
    _, count = score_profile(2, profile(), profile(parking="무료 주차", other_info=["예약 가능"]), "예약 가능")
    assert count["extra"] == 1 and count["invented"] == 1


def test_free_text_requires_gold_numbers_even_with_high_overlap():
    gold = profile(hours="매일 오전 10시부터 오후 6시까지 영업합니다")
    pred = profile(hours="매일 오전 11시부터 오후 6시까지 영업합니다")
    assert dice(gold["hours"], pred["hours"]) >= 0.5
    assert score_profile(2, gold, pred, gold["hours"])[1]["hit"] == 0
    assert score_profile(2, gold, pred, gold["hours"])[1]["invented"] == 1


def test_facts_in_wrong_field_do_not_hit():
    rows, count = score_profile(2, profile(parking="주말만 무료"), profile(other_info=["주말만 무료"]), "주말만 무료")
    assert count["hit"] == 0 and count["extra"] == 1
    assert any(row["field"] == "parking" and row["result"] == "miss" for row in rows)


def test_inferred_business_type_hits_even_if_source_does_not_say_it():
    _, count = score_profile(2, profile(business_type="고깃집"), profile(business_type="고깃집"), "삼겹살과 항정살을 팔아요")
    assert count["hit"] == 1 and count["invented"] == 0


def test_conflicts_use_presence_and_are_not_facts():
    gold = profile(needs_check=["월요일 휴무 / 연중무휴"])
    _, count = score_profile(2, gold, profile(needs_check=["휴무 확인 필요"]), "")
    assert count["conflict_hit"] == 1 and count["gold_facts"] == 0
    _, count = score_profile(2, profile(), profile(needs_check=["휴무 확인 필요"]), "")
    assert count["conflict_false"] == 1


def test_missing_and_error_files_stop_unless_allowed(score_root):
    with pytest.raises(ValueError, match="profile 없는 eval ID"):
        score_run("partial", root=score_root)
    gold = read_rows(score_root / "data/samples/answer_profiles_gold.jsonl")
    write_json(score_root / "experiments/runs/partial/2.json", {
        "id": 2, "prompt_version": "v1", "model": "test", "prompt_sha1": "test-sha",
        "profile": gold[2]["profile"],
    })
    write_json(score_root / "experiments/runs/partial/3.json", {"id": 3, "error": {"code": "FAILED"}})
    summary = score_run("partial", allow_missing=True, root=score_root)
    assert summary["n_scored"] == 1 and summary["n_missing"] == 24
    assert summary["recall_micro"] == 1.0


def test_mixed_run_metadata_is_rejected(score_root):
    gold = read_rows(score_root / "data/samples/answer_profiles_gold.jsonl")
    for row_id in (2, 3):
        write_json(score_root / f"experiments/runs/mixed/{row_id}.json", {
            "id": row_id, "prompt_version": "v1", "model": "test", "prompt_sha1": str(row_id),
            "profile": gold[row_id]["profile"],
        })
    with pytest.raises(ValueError, match="섞여"):
        score_run("mixed", allow_missing=True, root=score_root)


def test_allow_missing_records_even_an_entirely_missing_run(score_root):
    summary = score_run("empty", allow_missing=True, root=score_root)
    assert summary["n_scored"] == 0 and summary["n_missing"] == 25
    assert summary["recall_micro"] == summary["recall_macro"] == ""
    assert summary["model"] == ""
