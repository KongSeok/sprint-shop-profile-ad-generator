import json
import shutil
from unittest.mock import Mock

from app.schemas.copy import CopyGenerateResponse
from app.services.copy_generator import CopyGenerationError
from eval.common import ROOT
from tools import copy_samples


def output():
    return CopyGenerateResponse.model_validate({
        "instagram": {"body": "소개합니다\n만나보세요\n기다릴게요", "hashtags": ["#하나", "#둘", "#셋", "#넷", "#다섯"]},
        "delivery_app": {"body": "메뉴 소개입니다."}, "naver_place": {"body": "소개합니다. 만나보세요. 기다릴게요."},
    })


def test_samples_resume_skip_and_keep_successes_when_later_call_fails(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data/samples", tmp_path / "data/samples")
    generate = Mock(side_effect=[output(), CopyGenerationError("COPY_RETRY_LATER", "잠시 후 다시 눌러 주세요")])
    sleep = Mock()
    monkeypatch.setattr(copy_samples, "generate_copy", generate)
    monkeypatch.setattr(copy_samples.time, "sleep", sleep)
    assert copy_samples.run_samples([2, 8], root=tmp_path) == {"success": 1, "skipped": 0, "failed": 1}
    path = tmp_path / "data/copy_runs/copy_v1_menu.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["id"] for row in rows] == [2]
    assert rows[0]["input"]["menu"]["name"]
    generate.reset_mock()
    generate.side_effect = None
    generate.return_value = output()
    assert copy_samples.run_samples([2, 8], root=tmp_path) == {"success": 1, "skipped": 1, "failed": 0}
    generate.assert_called_once()
    assert [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines()] == [2, 8]
    sleep.assert_called_once_with(6)


def test_no_examples_sample_file_and_options(tmp_path, monkeypatch):
    shutil.copytree(ROOT / 'data/samples', tmp_path / 'data/samples')
    generate = Mock(return_value=output())
    monkeypatch.setattr(copy_samples,'generate_copy',generate)
    copy_samples.run_samples([2],version='v2',use_examples=False,features='숯불',this_time='이번 주만',root=tmp_path)
    assert (tmp_path/'data/copy_runs/copy_v2_noex_menu.jsonl').exists()
    assert not (tmp_path/'data/copy_runs/copy_v2.jsonl').exists()
    assert generate.call_args.kwargs['use_examples'] is False
    assert generate.call_args.args[1].features == '숯불'
    assert generate.call_args.args[1].this_time == '이번 주만'
