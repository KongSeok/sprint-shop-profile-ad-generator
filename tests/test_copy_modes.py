import json
from unittest.mock import Mock

import pytest

from app.schemas.copy import CopyMenu, GeneratedMenuCopy, GeneratedShopCopy
from app.schemas.profile import ShopProfile
from app.services.copy_pipeline import prepare_mode_prompt, run_checked_generation
from app.services.copy_quality import inspect_copy
from app.services.copy_quality import instagram_facts


def candidate(mode='menu'):
    data = {'instagram': {'body': ('바쁜 하루 사이 마음이 편해지는 순간을 그려요. 이야기 나누며 시간을 보내기에도 좋아요. '
                                '잠깐의 휴식이 필요한 날이라면 익숙한 자리로 걸음을 옮겨 보세요. '
                                '여유 있는 식탁에 앉아 작은 즐거움을 만나고, 하루의 속도를 조금 늦춰 보세요. 가벼운 발걸음으로 들르는 순간을 기다려요.'), 'hashtags': ['#가게', '#메뉴', '#식사', '#오늘', '#시간']}}
    if mode == 'menu':
        data['delivery_app'] = {'menu_description': '따뜻한 온기와 바삭한 식감을 담은 한 접시로 소개해요. 향긋한 한입의 맛을 가볍게 즐겨 보세요.'}
    else:
        data['delivery_app'] = {'shop_intro': '편안한 분위기에서 식사를 즐길 수 있도록 정성껏 준비했어요. 가벼운 식사부터 함께 나누는 한 상까지 기분 좋게 즐겨 보세요. 서로의 이야기가 자연스럽게 이어지는 자리예요.'}
        data['naver_place'] = {'body': '우리 가게\n\n' + '여유를 느끼고 싶을 때 편하게 머물기 좋은 자리를 생각했어요.\n입맛이 당기는 날 한 끼를 부담 없이 즐길 수 있게 준비했어요.\n소중한 사람과 이야기 나누며 기분 좋은 시간을 보내기 좋아요. 차분한 분위기에서 마음을 내려놓아도 좋아요.'}
    return data


@pytest.mark.parametrize('mode', ['shop', 'menu'])
def test_valid_result_requires_one_call(mode):
    data = candidate(mode)
    (GeneratedShopCopy if mode == 'shop' else GeneratedMenuCopy).model_validate(data)
    call = Mock(return_value=json.dumps(data))
    result = run_checked_generation(call, 'rules', '{}', {}, ShopProfile(shop_name=None, business_type=None),
                                    CopyMenu(name='라떼') if mode == 'menu' else None, mode, [])
    assert not result.regeneration.performed
    assert call.call_count == 1
    assert (result.naver_place is None) == (mode == 'menu')


def test_one_corrective_call_and_clean_second_selected():
    good = candidate()
    bad = candidate()
    bad['instagram']['body'] += ' (remove maybe)'
    call = Mock(side_effect=[json.dumps(bad), json.dumps(good)])
    result = run_checked_generation(call, 'rules', '{}', {}, ShopProfile(shop_name=None,business_type=None), CopyMenu(name='라떼'), 'menu', [])
    assert call.call_count == 2 and result.regeneration.selected_attempt == 2
    assert '문구에 편집 메모가 들어갔어요.' in result.regeneration.initial_violations
    assert result.warnings == []
    assert '다음 규칙을 어겼어' in call.call_args.args[0]


def test_both_invalid_choose_less_violations_and_warn():
    bad = candidate()
    bad['instagram']['body'] += ' (remove maybe)'
    worse = json.loads(json.dumps(bad))
    worse['delivery_app']['menu_description'] = '매력 풍미.'
    call = Mock(side_effect=[json.dumps(bad), json.dumps(worse)])
    result = run_checked_generation(call, 'rules', '{}', {}, ShopProfile(shop_name=None,business_type=None), CopyMenu(name='라떼'), 'menu', [])
    assert call.call_count == 2
    assert result.regeneration.selected_attempt == 1
    assert '문구에 편집 메모가 들어갔어요.' in result.warnings


def test_broken_json_gets_one_repair():
    call = Mock(side_effect=['broken', json.dumps(candidate())])
    result = run_checked_generation(call,'rules','{}',{},ShopProfile(shop_name=None,business_type=None),CopyMenu(name='라떼'),'menu',[])
    assert result.regeneration.selected_attempt == 2 and call.call_count == 2


def test_repetition_facts_lengths_and_odd_tail_detected():
    profile = ShopProfile(shop_name='가게',business_type='카페',menus=[{'name':'라떼','price':'4000원'}],hours='10~20시')
    data = candidate()
    data['instagram']['body'] = '라떼 4000원 10~20시 숯불 숯불 숯불 ? 🫧🌿'
    _, issues = inspect_copy(json.dumps(data), 'menu', profile, CopyMenu(name='라떼'))
    assert all(any(prefix in issue for issue in issues) for prefix in ['schema:', 'facts:', 'repetition:', 'odd_tail:'])


def test_mode_required_and_shop_requires_saved_profile(api_client, gemini_mock):
    for request in [
        {'profile': {'shop_name':None,'business_type':None},'menu':{'name':'라떼'}},
        {'mode':'shop','profile':{'shop_name':None,'business_type':None}},
        {'mode':'menu','shop_id':1},
        {'mode':'shop','shop_id':1,'menu':{'name':'라떼'}},
    ]:
        assert api_client.post('/copy/generate',json=request).status_code == 422
    gemini_mock.assert_not_called()


def test_business_type_claim_not_double_counted():
    profile = ShopProfile(shop_name='가게',business_type='동네 빵집')
    assert instagram_facts('동네 빵집에서 매일 빵을 만들어요.', profile) == ['business_type: 동네 빵집', '매일 생산']


def test_shop_api_uses_only_saved_profile(api_client, gemini_mock):
    from types import SimpleNamespace
    saved = api_client.post('/profile/save',json={'profile':{'shop_name':'가게','business_type':'카페'},'source_text':'원문','prompt_version':'v2'}).json()['shop_id']
    client = gemini_mock.return_value.__enter__.return_value
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(candidate('shop')))
    result = api_client.post('/copy/generate',json={'mode':'shop','shop_id':saved})
    assert result.status_code == 200
    assert 'shop_intro' in result.json()['delivery_app']
    assert 'naver_place' in result.json()
    contents = json.loads(client.models.generate_content.call_args.kwargs['contents'])
    assert set(contents) == {'profile'}


def test_menu_never_exposes_place_even_if_both_candidates_have_extra_key():
    data = candidate()
    data['naver_place'] = {'body':'불필요한 출력'}
    call = Mock(return_value=json.dumps(data))
    result = run_checked_generation(call,'rules','{}',{},ShopProfile(shop_name=None,business_type=None),CopyMenu(name='라떼'),'menu',[])
    assert call.call_count == 2 and result.naver_place is None


@pytest.mark.parametrize('mode', ['shop', 'menu'])
def test_prompt_inputs_schema_examples_and_style_priority(mode):
    profile = ShopProfile(shop_name='가게',business_type='고깃집',menus=[{'name':'삼겹살','price':None}])
    prompt, contents, examples, schema = prepare_mode_prompt(profile, CopyMenu(name='삼겹살'), mode, example_seed=42)
    assert ('menu' in json.loads(contents)) == (mode == 'menu')
    assert ('naver_place' in schema['properties']) == (mode == 'shop')
    full = [e for e in examples if e.get('kind') == 'full']
    styles = ('정중한 소개형','계절 인사 · 가게 이야기','준비 과정 · 사장님 일상')
    assert all(any(s in e['style'] for s in styles) == (mode == 'shop') for e in full)
    if mode == 'shop':
        assert all(e['channel'] != 'delivery_app' for e in examples)
        assert 'delivery_app.shop_intro' in prompt
    else:
        assert all(e['channel'] != 'naver_place' for e in examples)
        assert 'delivery_app.menu_description' in prompt


def test_consecutive_repeat_retries_once_and_trims(caplog):
    raw = json.dumps({
        'instagram': {'body': '남아요요요요', 'hashtags': ['#ABABAB', '#111', '#ㅋㅋㅋ']},
        'delivery_app': {'menu_description': '남아요요요요'},
    })
    call = Mock(return_value=raw)
    result = run_checked_generation(call, 'rules', '{}', {},
                                    ShopProfile(shop_name=None, business_type=None),
                                    CopyMenu(name='라테'), 'menu', [])
    assert call.call_count == 2
    assert result.delivery_app['menu_description'] == '남아요'
    assert result.instagram.body == '남아요'
    assert result.instagram.hashtags == ['#AB', '#111', '#ㅋㅋㅋ']
    assert '연속해서 반복된 글자는 정리했어요. 문구를 확인해 주세요.' in result.warnings
    assert all('consecutive_repeat' not in warning and 'delivery_app' not in warning for warning in result.warnings)
    assert 'consecutive_repeat' in caplog.text
    assert 'Trimmed consecutive copy repetition' in caplog.text



def test_repeat_cleanup_preserves_prices_and_units():
    from app.services.ad_copy import repeated_copy_fields, trim_repeated_copy

    text = {"body": "아메리카노 4,000원 · 10,000원 · 1000g · !!!"}
    assert repeated_copy_fields(text) == []
    assert trim_repeated_copy(text) == text
    assert trim_repeated_copy("남아요요요요") == "남아요"
