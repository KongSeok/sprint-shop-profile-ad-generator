import struct
import pytest
from app.schemas.profile import ShopProfile
from app.services import renderer
from test_renderer import chromium_available


def profile():
    return ShopProfile(shop_name='메뉴 가게', business_type='베이커리 카페', hours='10시~20시', closed_days=None, takeout_delivery='포장 가능', menus=[{'name': '소금빵', 'price': '3,000원'}])


@pytest.mark.parametrize('count,two_columns', [(6, False), (7, True), (12, True)])
def test_columns(count, two_columns):
    values = renderer.menu_board_values(profile(), [{'name': f'메뉴{i}', 'price': None} for i in range(count)])
    html, _ = renderer.fill_html('menu_board', values)
    assert ('class="menus two-columns"' in html) == two_columns
    assert '10시~20시' in html and '포장 가능' in html and 'None' not in html
    assert html.count('<article ') == count


def test_source_prices_and_empty_override():
    values = renderer.menu_board_values(profile())
    assert values['menus'][0]['price'] == '3,000원'
    with pytest.raises(renderer.RenderError, match='메뉴를 입력해 주세요'):
        renderer.menu_board_values(profile(), [])


def test_api_limits_and_empty(api_client, gemini_mock):
    body = {'profile': profile().model_dump(), 'menus': [{'name': '메뉴'}] * 13}
    response = api_client.post('/render/menu-board', json=body)
    assert response.status_code == 422 and '메뉴는 12개까지' in response.text
    body = {'profile': {'shop_name': None, 'business_type': None}}
    response = api_client.post('/render/menu-board', json=body)
    assert response.status_code == 422 and response.json()['detail'] == '메뉴를 입력해 주세요'
    gemini_mock.assert_not_called()


def test_menu_png():
    if not chromium_available():
        pytest.skip('playwright install chromium 필요')
    result = renderer.render_menu_board(profile())
    assert result.png.startswith(b'\x89PNG\r\n\x1a\n')
    assert struct.unpack('>II', result.png[16:24]) == (1080, 1527)
    assert result.warnings == []


def test_menu_tab_preview_download_without_generation(monkeypatch):
    import base64
    from streamlit.testing.v1 import AppTest
    from app.ui import api_client
    from eval.common import ROOT
    calls = []
    def api(base, method, path, **kwargs):
        calls.append(path)
        if path == '/profile/list':
            return [{'id': 1, 'shop_name': '가게', 'business_type': '카페'}]
        if path == '/profile/1':
            return {'profile': {'shop_name': '가게', 'business_type': '카페', 'menus': [{'name': '라떼', 'price': '4000원'}]},
                    'source_text': '', 'prompt_version': 'v2'}
        assert path == '/render/menu-board'
        return {'png_base64': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'warnings': ['확인 경고']}
    monkeypatch.setattr(api_client, 'request_api', api)
    view = AppTest.from_file(str(ROOT / 'app/ui/main_ui.py'), default_timeout=30).run()
    from ui_navigation import navigate

    view.selectbox(key='saved_selection').select(1).run()
    navigate(view, 'board')
    assert any(item.value == '사진 0/1개, 사진 없는 메뉴는 글자로만 나와요' for item in view.caption)
    next(button for button in view.button if button.label == '메뉴판 만들기').click().run()
    assert not view.exception
    assert '/render/menu-board' in calls and '/copy/generate' not in calls
    assert any(item.value == '확인 경고' for item in view.warning)
