import shutil
import struct
from pathlib import Path
import pytest
from app.schemas.profile import ShopProfile
from app.services import renderer
from app.services.renderer import TEMPLATES, RenderError, fill_html, select_theme, render_ad_card


def test_template_validation(tmp_path):
    shutil.copytree(TEMPLATES / 'ad_card', tmp_path / 'ad_card')
    path = tmp_path / 'ad_card/placeholder/template.html'
    path.write_text('{{ shop_name }}', encoding='utf-8')
    with pytest.raises(RenderError, match='필수 칸'):
        renderer.load_template('ad_card', root=tmp_path)
    (path.parent / 'meta.json').unlink()
    with pytest.raises(RenderError, match='meta.json'):
        renderer.load_template('ad_card', root=tmp_path)
    with pytest.raises(RenderError):
        renderer.load_template('ad_card', '../escape')


def test_themes_and_html():
    assert select_theme('숙성 돼지고기 전문점') == select_theme(None, '고깃집')
    assert select_theme('베이커리 카페') == select_theme(None, '빵집')
    assert select_theme('고깃집', '카페') == select_theme(None, '카페')
    assert select_theme('알 수 없음') == select_theme(None, '기본')
    values = dict(shop_name='<script>alert(1)</script>', menu_name='라떼', price=None, headline='안내', body='본문', photo_url=None)
    html, _ = fill_html('ad_card', values)
    assert '<script>alert' not in html and '&lt;script&gt;' in html
    assert 'class="price"' not in html


def chromium_available():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return Path(p.chromium.executable_path).exists()


def test_real_png_and_overflow():
    if not chromium_available():
        pytest.skip('playwright install chromium 필요')
    profile = ShopProfile(shop_name='한글 가게', business_type='카페')
    result = render_ad_card(profile, {'name': '라떼'}, {'headline': '긴 문장 ' * 40, 'body': '한글 본문'})
    assert result.png.startswith(b'\x89PNG\r\n\x1a\n')
    assert struct.unpack('>II', result.png[16:24]) == (1080, 1080)
    assert '글이 칸을 넘쳤어요: headline' in result.warnings


def test_api_no_gemini(api_client, monkeypatch, gemini_mock):
    monkeypatch.setattr(renderer, 'render_ad_card', lambda *a: renderer.RenderResult(b'png', ['warning']))
    result = api_client.post('/render/ad-card', json={'profile': {'shop_name': '가게', 'business_type': '카페'}, 'menu': {'name': '라떼'}, 'headline': '오늘', 'body': '소개'})
    assert result.status_code == 200 and result.json()['warnings'] == ['warning']
    assert api_client.post('/render/ad-card', json={'shop_id': 999, 'menu': {'name': '라떼'}, 'headline': '오늘', 'body': ''}).status_code == 404
    gemini_mock.assert_not_called()
