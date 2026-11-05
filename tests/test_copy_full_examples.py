import json
from collections import Counter

import pytest
from test_copy import copy_mock, copy_output

from app.core import config
from app.schemas.copy import CopyMenu
from app.schemas.profile import ShopProfile
from app.services.copy_examples import select_examples
from app.services.copy_generator import prepare_copy_prompt


@pytest.mark.parametrize('category', ['고깃집', '빵집', '카페', '한식', '일식', '분식'])
def test_full_examples_by_category(category):
    path = config.PROJECT_ROOT / 'data/copy_examples/examples.jsonl'
    picked = select_examples(path, category, example_version='full-v2')
    assert picked == select_examples(path, category, example_version='full-v2')
    instagram = [r for r in picked if r['channel'] == 'instagram']
    assert Counter(r['kind'] for r in instagram) == {'full': 2, 'short': 1}
    assert all(r['business_type'] == category for r in instagram)
    assert len({r['style'] for r in instagram if r['kind'] == 'full'}) == 2
    old = select_examples(path, category, example_version='short-v1')
    assert [r for r in picked if r['channel'] != 'instagram'] == [r for r in old if r['channel'] != 'instagram']
    assert all(r['kind'] == 'short' for r in old if r['channel'] == 'instagram')


def test_full_fallback_and_no_other_category_short(tmp_path):
    rows = [
        dict(id='a', channel='instagram', business_type='카페', kind='full', style='장면', text='A'),
        dict(id='b', channel='instagram', business_type='카페', kind='full', style='장면', text='B'),
        dict(id='c', channel='instagram', business_type='한식', kind='full', style='인사', text='C'),
        dict(id='d', channel='instagram', business_type='한식', kind='short', text='D'),
    ]
    path = tmp_path / 'examples.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    picked = select_examples(path, '카페', example_version='full-v2')
    assert len(picked) == 2 and all(r['kind'] == 'full' for r in picked)
    assert {r['style'] for r in picked} == {'장면', '인사'}
    assert any(r['business_type'] == '카페' for r in picked)
    assert select_examples(tmp_path / 'missing', '카페', example_version='full-v2') == []


def test_full_prompt_labels_and_metadata():
    prompt, _, picked = prepare_copy_prompt(ShopProfile(shop_name=None, business_type='고깃집'), CopyMenu(name='삼겹살'))
    assert '흐름·말투 참고 (문장 그대로 쓰지 말 것)' in prompt
    assert '짧은 표현 참고' in prompt
    grouped = json.loads(prompt.split('채널별 말투 예시:\n', 1)[1])
    assert len(grouped['instagram']['흐름·말투 참고 (문장 그대로 쓰지 말 것)']) == 2
    assert len(grouped['instagram']['짧은 표현 참고']) == 1
    expected_texts = [r['text'] for r in picked]
    assert all(value in expected_texts for group in grouped['instagram'].values() for value in group)


def test_old_selector_keeps_delivery_place_exactly(tmp_path):
    # Adding full posts must not consume RNG state for the two other channels.
    old = config.PROJECT_ROOT / 'data/copy_examples/examples.jsonl'
    rows = [json.loads(line) for line in old.read_text(encoding='utf-8-sig').splitlines()]
    original = tmp_path / 'old.jsonl'
    original.write_text('\n'.join(json.dumps(r) for r in rows if r.get('kind') != 'full'), encoding='utf-8')
    before = select_examples(original, '고깃집')
    after = select_examples(old, '고깃집', example_version='full-v2')
    assert [r for r in before if r['channel'] != 'instagram'] == [r for r in after if r['channel'] != 'instagram']


def test_one_full_uses_another_category_and_omits_missing_short(tmp_path):
    path = tmp_path / 'examples.jsonl'
    rows = [dict(id='a', channel='instagram', kind='full', business_type='카페', style='장면', text='A'),
            dict(id='b', channel='instagram', kind='full', business_type='한식', style='인사', text='B')]
    path.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    assert [r['id'] for r in select_examples(path, '카페', example_version='full-v2')] == ['a', 'b']


@pytest.mark.parametrize('version', ['short-v1', 'full-v2'])
def test_api_example_version(api_client, copy_mock, version):
    result = api_client.post('/copy/generate', json={
        'profile': {'shop_name': None, 'business_type': '고깃집'},
        'menu': {'name': '삼겹살'}, 'example_version': version,
    })
    assert result.status_code == 200
    prompt = copy_mock.models.generate_content.call_args.kwargs['config'].system_instruction
    assert ('흐름·말투 참고 (문장 그대로 쓰지 말 것)' in prompt) == (version == 'full-v2')


def test_invalid_example_version_does_not_call_model(api_client, gemini_mock):
    result = api_client.post('/copy/generate', json={
        'profile': {'shop_name': None, 'business_type': '고깃집'},
        'menu': {'name': '삼겹살'}, 'example_version': 'unknown',
    })
    assert result.status_code == 422
    gemini_mock.assert_not_called()
