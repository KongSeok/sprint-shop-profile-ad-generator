import json
import sqlite3
from unittest.mock import Mock
import pytest
from google.genai.errors import ClientError
from pydantic import ValidationError
from app.core import config
from app.schemas.concept import Concept, ConceptSuggestions
from app.schemas.profile import ShopProfile
from app.schemas.copy import CopyMenu
from app.services import concept_suggester, shop_store
from app.services.copy_generator import build_copy_prompt
from app.ui.concept_form import concept_from_form


def candidates():
    return [{'name': name, 'mood': mood, 'tone': tone, 'theme': '카페'} for name,mood,tone in
            [('정겨운 쉼표','정겨운 느낌','친근한 존댓말'), ('또렷한 한 잔','깔끔한 느낌','간결한 존댓말'), ('활기찬 하루','활기찬 느낌','경쾌한 존댓말')]]


def concept():
    return Concept(**candidates()[0], source='추천')


@pytest.mark.parametrize('field', ['mood_strengths', 'tone'])
def test_existing_preferences_never_call_model(api_client, gemini_mock, field):
    profile = ShopProfile(shop_name=None, business_type='카페', **{field:'있는 값'})
    with pytest.raises(concept_suggester.ConceptSuggestionError) as caught:
        concept_suggester.suggest_concepts(profile)
    assert caught.value.status_code == 409
    response = api_client.post('/profile/suggest-concept', json={'profile':profile.model_dump()})
    assert response.status_code == 409
    assert response.json()['detail']['message'] == '이미 분위기·말투가 있어요'
    gemini_mock.assert_not_called()


def test_recommendation_input_settings_and_theme_fallback(api_client, gemini_mock):
    client = gemini_mock.return_value.__enter__.return_value
    rows = candidates()
    rows[1]['theme'] = '허용하지 않은 테마'
    client.models.generate_content.return_value.text = json.dumps({'candidates':rows})
    profile = ShopProfile(shop_name='가게', business_type='카페', menus=[{'name':'라떼','price':'5000원'}], location='위치 비공개', other_info=['원문 비공개'])
    response = api_client.post('/profile/suggest-concept', json={'profile':profile.model_dump()})
    assert response.status_code == 200
    assert len(response.json()['candidates']) == 3 and response.json()['candidates'][1]['theme'] == '기본'
    call = client.models.generate_content.call_args.kwargs
    assert set(json.loads(call['contents'])) == {'shop_name','business_type','menus'}
    assert '위치 비공개' not in call['contents'] and '원문 비공개' not in call['contents']
    assert call['config'].temperature == 0.9
    assert call['config'].response_mime_type == 'application/json'
    assert call['config'].thinking_config.thinking_level.value == 'MEDIUM'
    assert gemini_mock.call_args.kwargs['http_options'].timeout == config.GEMINI_TIMEOUT_MS
    assert gemini_mock.call_args.kwargs['http_options'].retry_options.attempts == 1


@pytest.mark.parametrize('count', [0,2,4])
def test_exactly_three_candidates(count):
    with pytest.raises(ValidationError):
        ConceptSuggestions(candidates=(candidates()*2)[:count])


def test_distinct_names_and_moods():
    rows = candidates()
    rows[1] = rows[0]
    with pytest.raises(ValidationError):
        ConceptSuggestions(candidates=rows)
    with pytest.raises(ValidationError):
        Concept(**{**concept().model_dump(),'name':'열글자를넘어가는컨셉이름입니다'})


@pytest.mark.parametrize('status', [429,503,504,400])
def test_failure_is_safe_and_save_still_available(api_client, gemini_mock, status):
    client = gemini_mock.return_value.__enter__.return_value
    client.models.generate_content.side_effect = ClientError(status, {'error':{'message':'test-only-gemini-key'}})
    profile = {'shop_name':'가게','business_type':'카페'}
    response = api_client.post('/profile/suggest-concept', json={'profile':profile})
    assert response.status_code in (502,503)
    assert response.json()['detail']['message'] == '잠시 후 다시 눌러 주세요'
    assert 'test-only-gemini-key' not in response.text
    assert client.models.generate_content.call_count == 1
    saved = api_client.post('/profile/save', json={'profile':profile,'source_text':''})
    assert saved.status_code == 200


def test_save_load_clear_and_saved_shop_recommendation(api_client, gemini_mock):
    payload = {'profile':{'shop_name':'가게','business_type':'카페'}, 'source_text':'원문', 'concept':concept().model_dump()}
    saved = api_client.post('/profile/save', json=payload).json()['shop_id']
    loaded = api_client.get(f'/profile/{saved}').json()
    assert loaded['concept'] == concept().model_dump()
    assert 'concept' not in loaded['profile']
    client = gemini_mock.return_value.__enter__.return_value
    client.models.generate_content.return_value.text = json.dumps({'candidates':candidates()})
    assert api_client.post('/profile/suggest-concept', json={'shop_id':saved}).status_code == 200
    payload.update(shop_id=saved, concept=None)
    api_client.post('/profile/save', json=payload)
    assert api_client.get(f'/profile/{saved}').json()['concept'] is None
    assert api_client.post('/profile/suggest-concept', json={'shop_id':999}).status_code == 404


def test_legacy_database_migration_preserves_records(tmp_path):
    db = tmp_path / 'legacy.db'
    profile = ShopProfile(shop_name='기존 가게', business_type='카페')
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE shops (id INTEGER PRIMARY KEY, shop_name TEXT, business_type TEXT, profile_json TEXT, source_text TEXT, prompt_version TEXT, created_at TEXT, updated_at TEXT)')
        connection.execute('INSERT INTO shops VALUES (1,?,?,?,?,?,?,?)', ('기존 가게','카페',profile.model_dump_json(),'원문','v2','before','before'))
    shop_store.init_db(db)
    shop_store.init_db(db)
    loaded = shop_store.get_shop(1, db_path=db)
    assert loaded['concept'] is None and loaded['source_text'] == '원문'
    shop_store.save_shop(profile,'수정','v2',1,concept=concept(),db_path=db)
    assert shop_store.get_shop(1,db_path=db)['concept']['source'] == '추천'


def test_source_changes_on_owner_edits():
    original = candidates()[0]
    assert concept_from_form(original, original)['source'] == '추천'
    changed = {**original,'mood':'다르게 적은 분위기'}
    assert concept_from_form(changed, original)['source'] == '직접'
    assert concept_from_form(original)['source'] == '직접'
    assert concept_from_form({}) is None
    saved_direct = {**original,'source':'직접'}
    assert concept_from_form(original, saved_direct)['source'] == '직접'


@pytest.mark.parametrize('version', ['v1','v2'])
def test_copy_concept_is_style_only_and_profile_wins(version):
    menu = CopyMenu(name='라떼')
    profile = ShopProfile(shop_name=None,business_type=None)
    prompt, contents = build_copy_prompt(profile,menu,version,concept=concept())
    assert json.loads(contents)['concept'] == {'mood':concept().mood,'tone':concept().tone}
    assert '사장님이 고른 컨셉. 사실이 아니니 사실처럼 쓰지 않기' in prompt
    for field in ('tone','mood_strengths'):
        richer = profile.model_copy(update={field:'원래 값'})
        prompt, contents = build_copy_prompt(richer,menu,version,concept=concept())
        assert 'concept' not in json.loads(contents)
        assert '사장님이 고른 컨셉' not in prompt


def test_saved_concept_used_for_copy_api(api_client, monkeypatch):
    from app.api.routers import copy as copy_router
    from test_copy_samples import output
    saved = api_client.post('/profile/save',json={'profile':{'shop_name':'가게','business_type':'카페'},'source_text':'','concept':concept().model_dump()}).json()['shop_id']
    from app.schemas.copy import ModeCopyResponse
    old = output()
    generate = Mock(return_value=ModeCopyResponse(mode='menu', instagram=old.instagram, delivery_app={'menu_description':old.delivery_app.body}))
    monkeypatch.setattr(copy_router,'generate_copy',generate)
    assert api_client.post('/copy/generate',json={"mode": "menu", 'shop_id':saved,'menu':{'name':'라떼'}}).status_code == 200
    assert generate.call_args.kwargs['concept'] == concept().model_dump()


def test_theme_keys_follow_template_file(tmp_path,monkeypatch):
    from app.schemas.concept import allowed_themes
    (tmp_path/'templates').mkdir()
    (tmp_path/'templates/themes.json').write_text(json.dumps({'새테마':{},'기본':{}}),encoding='utf-8')
    monkeypatch.setattr(config,'PROJECT_ROOT',tmp_path)
    assert allowed_themes() == ['새테마','기본']
    assert Concept(**{**concept().model_dump(),'theme':'새테마'}).theme == '새테마'


def test_concept_numbers_do_not_become_fact_evidence(gemini_mock):
    from app.services.copy_generator import generate_copy
    from test_copy_samples import output
    result = output().model_dump(exclude={'warnings','example_ids'})
    result['delivery_app']['body'] = '15000원 메뉴입니다.'
    gemini_mock.return_value.__enter__.return_value.models.generate_content.return_value.text = json.dumps(result)
    selected = concept().model_copy(update={'mood':'15000원 같은 느낌'})
    generated = generate_copy(ShopProfile(shop_name=None,business_type=None),CopyMenu(name='라떼'),'v1',concept=selected)
    assert any('15000' in warning for warning in generated.warnings)
