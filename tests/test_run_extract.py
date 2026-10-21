import hashlib
import json
import shutil
from unittest.mock import Mock

import pytest

from app.services.profile_extractor import ProfileExtractionError, extract_profile_raw
from app.schemas.profile import ShopProfile
from eval import run_extract as runner
from eval.common import ROOT, read_json, write_json


@pytest.fixture
def run_setup(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data/samples", tmp_path / "data/samples")
    monkeypatch.setattr(runner, "build_prompt", lambda version: f"full-system-{version}")
    sleep = Mock()
    monkeypatch.setattr(runner.time, "sleep", sleep)
    profile = ShopProfile(shop_name=None, business_type=None)
    call = Mock(return_value=(profile.model_dump_json(), profile))
    monkeypatch.setattr(runner, "extract_profile_raw", call)
    return tmp_path, call, sleep


def test_cached_success_skips_call_and_force_calls_again(run_setup):
    root, call, sleep = run_setup
    assert runner.run_extract("v1", ids=[2], root=root)["success"] == 1
    stored = read_json(root / "experiments/runs/v1/2.json")
    assert stored["raw_text"] == call.return_value[0]
    assert stored["prompt_sha1"] == hashlib.sha1(b"full-system-v1").hexdigest()
    call.reset_mock()
    assert runner.run_extract("v1", ids=[2], root=root)["skipped"] == 1
    call.assert_not_called()
    sleep.assert_not_called()
    assert runner.run_extract("v1", ids=[2], force=True, root=root)["success"] == 1
    call.assert_called_once()


@pytest.mark.parametrize("changed", ["model", "prompt_sha1"])
def test_changed_cache_metadata_calls_again(run_setup, changed):
    root, call, _ = run_setup
    runner.run_extract("v1", ids=[2], root=root)
    path = root / "experiments/runs/v1/2.json"
    record = read_json(path)
    record[changed] = "different"
    write_json(path, record)
    call.reset_mock()
    runner.run_extract("v1", ids=[2], root=root)
    call.assert_called_once()


@pytest.mark.parametrize("bad", ["error", "invalid_profile"])
def test_error_or_invalid_cached_profile_is_retried(run_setup, bad):
    root, call, _ = run_setup
    runner.run_extract("v1", ids=[2], root=root)
    path = root / "experiments/runs/v1/2.json"
    record = read_json(path)
    if bad == "error":
        record["error"] = {"code": "FAILED"}
    else:
        record["profile"] = {}
    write_json(path, record)
    call.reset_mock()
    assert runner.run_extract("v1", ids=[2], root=root)["success"] == 1
    call.assert_called_once()


@pytest.mark.parametrize("status", [429, 503])
def test_retry_then_success_and_interval(run_setup, status):
    root, call, sleep = run_setup
    success = call.return_value
    call.side_effect = [ProfileExtractionError("GEMINI_CALL_FAILED", "busy", 502, upstream_status=status), success, success]
    counts = runner.run_extract("v1", ids=[2, 3], root=root)
    assert counts["success"] == 2 and counts["failed"] == 0
    assert [args.args[0] for args in sleep.call_args_list] == [30, 6]


def test_exhausted_backoff_stops_and_preserves_resumable_errors(run_setup):
    root, call, sleep = run_setup
    success = call.return_value
    call.side_effect = ProfileExtractionError("GEMINI_CALL_FAILED", "busy", 502, upstream_status=429)
    counts = runner.run_extract("v1", ids=[2, 3], root=root)
    assert counts["failed"] == 1 and counts["stopped"]
    assert call.call_count == 4
    assert [args.args[0] for args in sleep.call_args_list] == [30, 60, 120]
    assert read_json(root / "experiments/runs/v1/2.json")["error"]["upstream_status"] == 429
    assert not (root / "experiments/runs/v1/3.json").exists()
    call.side_effect = None
    call.return_value = success
    call.reset_mock()
    assert runner.run_extract("v1", ids=[2, 3], root=root)["success"] == 2
    assert call.call_count == 2


def test_train_id_rejected_before_call(run_setup):
    root, call, _ = run_setup
    with pytest.raises(ValueError, match="train"):
        runner.run_extract("v1", ids=[1, 2], root=root)
    call.assert_not_called()


def test_raw_validation_failure_is_saved_without_key_leak(run_setup, capsys):
    root, call, _ = run_setup
    call.side_effect = ProfileExtractionError(
        "PROFILE_VALIDATION_FAILED", "bad test-only-gemini-key", 502,
        raw_text='{"shop_name": 123, "note": "test-only-gemini-key"}',
    )
    counts = runner.run_extract("v1", ids=[2], root=root)
    saved = (root / "experiments/runs/v1/2.json").read_text(encoding="utf-8")
    assert counts["failed"] == 1 and "test-only-gemini-key" not in saved
    assert "123" in read_json(root / "experiments/runs/v1/2.json")["raw_text"]
    assert "test-only-gemini-key" not in capsys.readouterr().out


def test_service_keeps_raw_text_for_validation_failure(gemini_mock):
    response = gemini_mock.return_value.__enter__.return_value.models.generate_content.return_value
    response.text = '{"shop_name": 123, "business_type": null}'
    with pytest.raises(ProfileExtractionError) as caught:
        extract_profile_raw("소개", "v1")
    assert caught.value.raw_text == response.text


def test_service_keeps_gemini_upstream_code(gemini_mock):
    from google.genai.errors import ClientError
    gemini_mock.return_value.__enter__.return_value.models.generate_content.side_effect = ClientError(
        429, {"error": {"message": "quota"}}
    )
    with pytest.raises(ProfileExtractionError) as caught:
        extract_profile_raw("소개", "v1")
    assert caught.value.upstream_status == 429
