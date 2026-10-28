"""Offline Jinja2 + Chromium renderer. Never calls an LLM."""
import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, StrictUndefined, meta
from playwright.sync_api import sync_playwright, Error as PlaywrightError

from app.core.config import PROJECT_ROOT
from app.services.copy_examples import business_category

TEMPLATES = PROJECT_ROOT / 'templates'
REQUIRED_FIELDS = {'ad_card': {'shop_name', 'menu_name', 'price', 'headline', 'body', 'photo_url'},
                   'menu_board': {'shop_name', 'menus', 'footer'}}


@dataclass
class RenderResult:
    png: bytes
    warnings: list[str]


class RenderError(ValueError):
    pass


def load_template(kind, template='placeholder', *, root=TEMPLATES):
    if kind not in REQUIRED_FIELDS or not re.fullmatch(r'[a-zA-Z0-9_-]+', template):
        raise RenderError('템플릿 이름을 확인해 주세요')
    folder = root / kind / template
    try:
        metadata = json.loads((folder / 'meta.json').read_text(encoding='utf-8'))
        html = (folder / 'template.html').read_text(encoding='utf-8')
        css = (folder / 'style.css').read_text(encoding='utf-8')
        size = metadata['size']
        if any(type(size[key]) is not int or not 1 <= size[key] <= 4096 for key in ('width', 'height')):
            raise ValueError('size')
        for key in ('name', 'source', 'license'):
            if not metadata.get(key):
                raise ValueError(key)
        env = Environment(autoescape=True, undefined=StrictUndefined)
        missing = REQUIRED_FIELDS[kind] - meta.find_undeclared_variables(env.parse(html))
        if missing:
            raise RenderError('템플릿 필수 칸이 없습니다: ' + ', '.join(sorted(missing)))
        return env.from_string(html), css, metadata
    except (OSError, KeyError, ValueError, TypeError) as exc:
        if isinstance(exc, RenderError):
            raise
        raise RenderError('템플릿 파일 또는 meta.json을 확인해 주세요') from exc


def select_theme(business_type, theme=None, *, root=TEMPLATES):
    themes = json.loads((root / 'themes.json').read_text(encoding='utf-8'))
    name = theme if theme is not None else business_category(business_type)
    if theme is not None and name not in themes:
        raise RenderError('테마를 찾을 수 없습니다')
    return themes.get(name, themes['기본'])


def fill_html(kind, values, *, template='placeholder', theme=None, business_type=None, root=TEMPLATES):
    compiled, css, metadata = load_template(kind, template, root=root)
    selected = select_theme(business_type, theme, root=root)
    if any(not re.fullmatch(r'#[0-9A-Fa-f]{6}', selected[key]) for key in ('color_bg', 'color_main', 'color_accent')):
        raise RenderError('테마 색상을 확인해 주세요')
    # Only the bundled OFL font is supported; all resources are embedded for offline rendering.
    font = base64.b64encode((root / 'fonts/NotoSansKR.ttf').read_bytes()).decode()
    variables = ';'.join(f'--{key.replace("_", "-")}:{json.dumps(value) if key.startswith("font") else value}' for key, value in selected.items())
    theme_css = '@font-face{font-family:"Noto Sans KR";src:url(data:font/ttf;base64,' + font + ');font-weight:100 900} :root{' + variables + '}'
    return compiled.render(**values, theme_css=theme_css, style_css=css), metadata


def screenshot(html, metadata):
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport=metadata['size'], device_scale_factor=1)
                page.route('**/*', lambda route: route.abort())
                page.set_content(html, wait_until='load')
                page.evaluate('document.fonts.ready')
                page.evaluate("Promise.all(Array.from(document.images).map(i => i.decode().catch(() => {})))")
                fields = page.locator('[data-field]').evaluate_all("els => els.filter(e => e.scrollHeight > e.clientHeight + 1 || e.scrollWidth > e.clientWidth + 1).map(e => e.dataset.field)")
                warnings = ['글이 칸을 넘쳤어요: ' + name for name in dict.fromkeys(fields)]
                if page.evaluate('document.documentElement.scrollHeight > innerHeight + 1'):
                    warnings.append('글이 칸을 넘쳤어요: page')
                return RenderResult(page.screenshot(type='png'), warnings)
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise RenderError('Chromium을 실행하지 못했어요. playwright install chromium을 확인해 주세요') from exc


def render_ad_card(profile, menu, copy_text, template='placeholder', theme=None):
    menu = menu.model_dump() if hasattr(menu, 'model_dump') else menu
    values = dict(shop_name=profile.shop_name or '', menu_name=menu['name'], price=menu.get('price'),
                  headline=copy_text['headline'], body=copy_text['body'], photo_url=copy_text.get('photo_url'))
    if values['photo_url'] and not values['photo_url'].startswith(('data:image/png;base64,', 'data:image/jpeg;base64,')):
        raise RenderError('사진은 PNG 또는 JPEG 데이터만 사용할 수 있습니다')
    html, metadata = fill_html('ad_card', values, template=template, theme=theme, business_type=profile.business_type)
    return screenshot(html, metadata)


def menu_board_values(profile, menus=None):
    chosen = menus if menus is not None else profile.menus
    if not chosen:
        raise RenderError('메뉴를 입력해 주세요')
    if len(chosen) > 12:
        raise RenderError('메뉴는 12개까지')
    rows = [item.model_dump() if hasattr(item, 'model_dump') else dict(item) for item in chosen]
    for row in rows:
        if not isinstance(row.get('name'), str) or not row['name'].strip():
            raise RenderError('메뉴 이름을 입력해 주세요')
        row.setdefault('price', None)
        row.setdefault('note', None)
    footer = [value for value in (profile.hours, profile.closed_days, profile.takeout_delivery) if value]
    return dict(shop_name=profile.shop_name or '', menus=rows, footer=footer)


def render_menu_board(profile, menus=None, template='placeholder', theme=None):
    values = menu_board_values(profile, menus)
    html, metadata = fill_html('menu_board', values, template=template, theme=theme, business_type=profile.business_type)
    return screenshot(html, metadata)
