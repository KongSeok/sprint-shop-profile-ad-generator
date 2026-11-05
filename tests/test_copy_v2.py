from test_copy import copy_mock, copy_output
import json
from app.schemas.copy import CopyMenu
from app.schemas.profile import ShopProfile
from app.services.copy_examples import business_category, select_examples, example_warnings
from app.services.copy_generator import build_copy_prompt


def test_categories():
    assert business_category("고깃집") == "고깃집"
    assert [business_category(s) for s in ['베이커리 카페', '숙성 돼지고기 전문점', '일본 가정식집', '알 수 없음']] == ['빵집', '고깃집', '일식', None]


def test_selection(tmp_path):
    path = tmp_path / 'examples.jsonl'
    rows = [dict(id=str(i), channel=c, business_type='카페' if i < 3 else '한식', text=f'문구{i}') for c in ('instagram', 'delivery_app', 'naver_place', 'ignored') for i in range(5)]
    path.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    picked = select_examples(path, '카페')
    assert picked == select_examples(path, '카페')
    assert len(picked) == 9 and all(r['business_type'] == '카페' for r in picked)
    assert select_examples(tmp_path / 'absent', None) == []
    path.write_text('', encoding='utf-8')
    assert select_examples(path, None) == []


def test_versions_and_metadata():
    profile = ShopProfile(shop_name=None, business_type='카페')
    v1, _ = build_copy_prompt(profile, CopyMenu(name='라떼'), 'v1')
    v2, _ = build_copy_prompt(profile, CopyMenu(name='라떼'), 'v2')
    assert '채널별 말투 예시:' not in v1 and '채널별 말투 예시:' in v2
    assert 'account' not in v2 and 'source_kind' not in v2


def test_v3_2_prompt_focuses_on_menu_instead_of_listing_facts():
    from app.core import config

    saved_prompt = (config.PROJECT_ROOT / 'app/prompts/copy_v3-2.txt').read_text(encoding='utf-8')
    prompt, _ = build_copy_prompt(
        ShopProfile(shop_name=None, business_type='카페'),
        CopyMenu(name='에스프레소'), 'v2', use_examples=False,
    )
    assert prompt == saved_prompt
    assert '목표는 읽는 사람이 이 메뉴를 먹고 싶고 가게에 가고 싶어지게 만드는 것입니다.' in prompt
    assert '나열하지 마세요' in prompt


def test_leak_warnings():
    examples = [{'text': '15000원 한우등심', 'menu_names': ['한우등심']}]
    assert len(example_warnings(examples, '라떼 13000원', '한우등심 15000원')) == 2


def test_bad_version(api_client, gemini_mock):
    result = api_client.post('/copy/generate', json={'profile': {'shop_name': None, 'business_type': None}, 'menu': {'name': '라떼'}, 'prompt_version': 'v3'})
    assert result.status_code == 422
    gemini_mock.assert_not_called()


def test_v2_missing_file_warns_without_network(copy_mock, monkeypatch, tmp_path):
    from app.core import config
    from app.services.copy_generator import generate_copy
    import shutil
    shutil.copytree(config.PROJECT_ROOT / 'app/prompts', tmp_path / 'app/prompts')
    monkeypatch.setattr(config, 'PROJECT_ROOT', tmp_path)
    result = generate_copy(ShopProfile(shop_name=None, business_type=None), CopyMenu(name='라떼'))
    assert result.example_ids == []
    assert any('예시 파일' in value for value in result.warnings)


import re
from unittest.mock import Mock
import pytest
from pydantic import ValidationError
from app.schemas.copy import GeneratedCopyV2, GeneratedCopy
from app.services import copy_generator


@pytest.mark.parametrize('version,use_examples', [('v1', True), ('v1', False), ('v2', False)])
def test_disabled_examples_do_not_load_or_check(copy_mock, monkeypatch, version, use_examples):
    loader = Mock(side_effect=AssertionError('examples must not load'))
    checker = Mock(side_effect=AssertionError('leak check must not run'))
    monkeypatch.setattr(copy_generator, 'select_examples', loader)
    monkeypatch.setattr(copy_generator, 'example_warnings', checker)
    profile = ShopProfile(shop_name=None, business_type=None)
    result = copy_generator.generate_copy(profile, CopyMenu(name='라떼'), version, use_examples=use_examples)
    assert result.example_ids == [] and result.warnings == []
    loader.assert_not_called()
    checker.assert_not_called()


def test_v2_keeps_instagram_flexible_and_shortens_other_channels():
    profile = ShopProfile(shop_name=None, business_type=None)
    prompt, _ = build_copy_prompt(profile, CopyMenu(name='라떼'), 'v2', use_examples=False)
    instagram_rule = next(line for line in prompt.splitlines() if line.startswith('16.'))
    assert not re.search(r'\d+\s*[~~～–-]\s*\d+\s*(줄|문장)', instagram_rule)
    assert '정확히 2문장' in prompt and '소개 3~4줄' in prompt
    assert '장면 규칙은 인스타그램에만 적용' in prompt
    assert '세 채널 중 한 곳에서만 한 번' in prompt
    assert GeneratedCopyV2.model_json_schema()['$defs']['InstagramCopyV2']['properties']['body']['minLength'] == 150


@pytest.mark.parametrize('channel,minimum,maximum', [('instagram',150,600),('delivery_app',40,80),('naver_place',120,220)])
def test_v2_character_boundaries(copy_output, channel, minimum, maximum):
    for size in (minimum, maximum):
        copy_output[channel]['body'] = '가' * size
        GeneratedCopyV2.model_validate(copy_output)
    for size in (minimum-1, maximum+1):
        copy_output[channel]['body'] = '가' * size
        with pytest.raises(ValidationError):
            GeneratedCopyV2.model_validate(copy_output)


def test_v2_allows_one_line_and_fifteen_hashtags(copy_output):
    copy_output['instagram']['body'] = '가' * 150
    copy_output['instagram']['hashtags'] = ['#태그'] * 15
    GeneratedCopyV2.model_validate(copy_output)
    with pytest.raises(ValidationError):
        GeneratedCopy.model_validate(copy_output)


def test_v2_leak_mock_response(copy_mock, monkeypatch, copy_output):
    examples = [{'id':'test', 'channel':'instagram', 'text':'한우등심 15000원', 'menu_names':['한우등심']}]
    monkeypatch.setattr(copy_generator,'select_examples',Mock(return_value=examples))
    copy_output['instagram']['body'] += ' 한우등심 15000원'
    copy_mock.models.generate_content.return_value.text = json.dumps(copy_output)
    result = copy_generator.generate_copy(ShopProfile(shop_name=None,business_type=None),CopyMenu(name='라떼'))
    assert result.example_ids == ['test']
    assert any(w == '예시 내용이 섞였어요: 한우등심' for w in result.warnings)
    assert any(w == '예시 내용이 섞였어요: 15000' for w in result.warnings)


def test_api_passes_use_examples_false(api_client, copy_mock, monkeypatch):
    checker = Mock(side_effect=AssertionError('must not run'))
    monkeypatch.setattr(copy_generator,'example_warnings',checker)
    result = api_client.post('/copy/generate',json={'profile':{'shop_name':None,'business_type':None},'menu':{'name':'라떼'},'use_examples':False})
    assert result.status_code == 200 and result.json()['example_ids'] == []
    assert '채널별 말투 예시:' not in copy_mock.models.generate_content.call_args.kwargs['config'].system_instruction
    checker.assert_not_called()


def test_short_channels_emit_one_combined_warning(api_client, copy_mock, copy_output):
    copy_output['delivery_app']['body'] = '짧은 메뉴.'
    copy_output['naver_place']['body'] = '짧은 소개.'
    copy_mock.models.generate_content.return_value.text = json.dumps(copy_output)
    result = api_client.post('/copy/generate', json={
        'profile': {'shop_name': None, 'business_type': None}, 'menu': {'name': '라떼'},
    })
    assert result.status_code == 502
    assert result.json()['detail']['code'] == 'COPY_LENGTH_BELOW_MIN'
    assert result.json()['detail']['message'].count('글자 수 하한 미달') == 1
    assert '배달앱, 네이버 플레이스' in result.json()['detail']['message']
