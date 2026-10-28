from streamlit.testing.v1 import AppTest
from app.schemas.profile import ShopProfile
from app.ui import api_client
from app.ui.api_client import UserApiError
from eval.common import ROOT
from test_concept import candidates


def button(view, label):
    return next(item for item in view.button if item.label == label)


def test_choose_edit_save_reload_concept(monkeypatch):
    saved = {}
    calls = []
    profile = ShopProfile(shop_name='우리 가게', business_type='카페').model_dump()
    def api(base, method, path, *, payload=None, **kwargs):
        calls.append(path)
        if path == '/profile/list':
            return [{'id':1,'shop_name':'우리 가게','business_type':'카페'}] if saved else []
        if path == '/profile/extract':
            return profile
        if path == '/profile/suggest-concept':
            assert payload['profile']['shop_name'] == '화면 수정 이름'
            return {'candidates':candidates()}
        if path == '/profile/save':
            saved.update(payload,shop_id=1)
            return {'shop_id':1}
        if path == '/profile/1':
            return dict(saved)
        raise AssertionError(path)
    monkeypatch.setattr(api_client,'request_api',api)
    view = AppTest.from_file(str(ROOT / 'app/ui/main_ui.py'),default_timeout=30).run()
    view.text_area(key='source_input').input('가게 소개')
    button(view,'정리하기').click().run()
    view.text_input(key='draft_1_shop_name').input('화면 수정 이름').run()
    button(view,'컨셉 추천받기').click().run()
    assert not view.exception
    view.radio(key='concept_1_1_choice').set_value(0).run()
    view.text_input(key='concept_1_1_0_mood').input('내가 고친 분위기').run()
    button(view,'저장').click().run()
    assert not view.exception
    assert saved['concept']['mood'] == '내가 고친 분위기'
    assert saved['concept']['source'] == '직접'
    assert 'concept' not in saved['profile']
    view.selectbox(key='saved_selection').select(1).run()
    button(view,'불러오기').click().run()
    assert not view.exception
    assert view.text_input(key='concept_2_0_saved_mood').value == '내가 고친 분위기'
    button(view,'저장').click().run()
    assert saved['concept']['source'] == '직접'


def test_recommend_failure_does_not_block_save(monkeypatch):
    saved = []
    def api(base, method, path, *, payload=None, **kwargs):
        if path == '/profile/list':
            return []
        if path == '/profile/extract':
            return ShopProfile(shop_name='가게',business_type='카페').model_dump()
        if path == '/profile/suggest-concept':
            raise UserApiError('잠시 후 다시 눌러 주세요')
        if path == '/profile/save':
            saved.append(payload)
            return {'shop_id':1}
        raise AssertionError(path)
    monkeypatch.setattr(api_client,'request_api',api)
    view = AppTest.from_file(str(ROOT / 'app/ui/main_ui.py'),default_timeout=30).run()
    view.text_area(key='source_input').input('가게 소개')
    button(view,'정리하기').click().run()
    button(view,'컨셉 추천받기').click().run()
    assert not view.exception and any('잠시 후' in w.value for w in view.warning)
    button(view,'저장').click().run()
    assert not view.exception and saved[0]['concept'] is None
