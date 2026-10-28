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
