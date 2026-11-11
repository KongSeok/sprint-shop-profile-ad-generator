"""Offline Jinja2 + Chromium renderer. Never calls an LLM."""
import base64
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache

from jinja2 import Environment, StrictUndefined, meta
from playwright.sync_api import sync_playwright, Error as PlaywrightError

from app.core.config import PROJECT_ROOT
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from app.services.cutout_policy import analyze_mask, FOREGROUND_MIN_ALPHA, PARTIAL_HINT_RATIO
from app.services import template_v3
from app.services.fact_check import ORIGIN_PATTERN
from app.services.design_options import catalog, default_design, variables

TEMPLATES = PROJECT_ROOT / 'templates'
REQUIRED_FIELDS = {'ad_card': {'shop_name', 'menu_name', 'price', 'body', 'photo_url'},
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
        if metadata.get('fit_v3'):
            return Environment(autoescape=True).from_string(html), css, metadata
        env = Environment(autoescape=True, undefined=StrictUndefined)
        missing = REQUIRED_FIELDS[kind] - meta.find_undeclared_variables(env.parse(html))
        if missing:
            raise RenderError('템플릿 필수 칸이 없습니다: ' + ', '.join(sorted(missing)))
        return env.from_string(html), css, metadata
    except (OSError, KeyError, ValueError, TypeError) as exc:
        if isinstance(exc, RenderError):
            raise
        raise RenderError('템플릿 파일 또는 meta.json을 확인해 주세요') from exc


FONT_FILES = {
    'Noto Sans KR': 'NotoSansKR.ttf',
    'Nanum Myeongjo': 'NanumMyeongjo-Regular.ttf',
    'Gowun Dodum': 'GowunDodum-Regular.ttf',
    'Black Han Sans': 'BlackHanSans-Regular.ttf',
    'Do Hyeon': 'DoHyeon-Regular.ttf',
    'Jua': 'Jua-Regular.ttf',
}


def resolve_theme(business_type, theme, design):
    legacy = {'카페', '빵집', '고깃집', '일식', '한식', '기본'}
    if design is None and theme is not None and theme not in legacy:
        raise RenderError('테마를 찾을 수 없습니다')
    return design or default_design(theme or business_type)


def select_theme(business_type, theme=None, *, root=TEMPLATES, design=None):
    return variables(resolve_theme(business_type, theme, design), catalog(root))


@lru_cache
def font_face(root, family):
    encoded = base64.b64encode((root / 'fonts' / FONT_FILES[family]).read_bytes()).decode()
    weight = '100 900' if family == 'Noto Sans KR' else '400'
    return f'@font-face{{font-family:"{family}";src:url(data:font/ttf;base64,{encoded});font-weight:{weight}}}'


def fill_html(kind, values, *, template='placeholder', theme=None, business_type=None, root=TEMPLATES, design=None):
    compiled, css, metadata = load_template(kind, template, root=root)
    if metadata.get('fit_v3'):
        values = template_v3.render_context(values, business_type, design, root)
        return compiled.render(**values, style_css=css), metadata
    selected = select_theme(business_type, theme, root=root, design=design)
    families = dict.fromkeys((selected['font_title'], selected['font_body'], 'Noto Sans KR'))
    declarations = ';'.join(f'--{key.replace("_", "-")}:{json.dumps(value) if key.startswith("font") else value}'
                            for key, value in selected.items())
    theme_css = ''.join(font_face(root, family) for family in families) + ':root{' + declarations + '}'
    values = {'title_height': 280, 'intro': '', **values}
    return compiled.render(**values, theme_css=theme_css, style_css=css), metadata


@contextmanager
def open_browser():
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except PlaywrightError as exc:
                if "Executable doesn't exist" not in str(exc):
                    raise
                browser = playwright.chromium.launch(channel='msedge')
            try:
                yield browser
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise RenderError('Chromium을 실행하지 못했어요. playwright install chromium을 확인해 주세요') from exc


def fit_cutout_titles(page):
    page.locator('[data-cutout-title]').evaluate_all('''elements => {
        for (const el of elements) {
            let size = parseInt(getComputedStyle(el).fontSize, 10);
            const limit = Number(el.dataset.cutoutTitle);
            while (size > 24 && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > limit)) {
                el.style.fontSize = (--size) + "px";
                if (size < 48 && getComputedStyle(el).fontFamily.includes('Black Han Sans'))
                    el.style.fontFamily = 'var(--font-body), sans-serif';
            }
        }
    }''')


def capture(browser, html, metadata):
    page = browser.new_page(viewport=metadata['size'], device_scale_factor=1)
    try:
        if metadata.get('fit_v3'):
            def asset(route):
                url = route.request.url
                if url == 'https://render.invalid/out/card.html':
                    return route.fulfill(body=html, content_type='text/html; charset=utf-8')
                match = re.fullmatch(r'https://render.invalid/fonts/([A-Za-z0-9_-]+\.ttf)', url)
                if match:
                    font = TEMPLATES / 'fonts' / match[1]
                    if font.is_file():
                        return route.fulfill(path=font, content_type='font/ttf')
                route.abort()

            page.route('**/*', asset)
            page.goto('https://render.invalid/out/card.html', wait_until='load')
            page.wait_for_selector('body[data-ready]', timeout=20000)
            warnings = page.locator('[data-overflow="wrap"], [data-overflow="menus"]').evaluate_all(
                "els => els.map(el => '글이 칸을 넘쳤어요: ' + (el.dataset.field || el.dataset.overflow))"
            )
            if page.locator('[data-field="body"]').evaluate_all("els => els.some(e => e.scrollHeight > e.clientHeight + 1)"):
                warnings.append('글이 칸을 넘쳤어요: body')
            return RenderResult(page.screenshot(type='png'), warnings)
        page.route('**/*', lambda route: route.abort())
        page.set_content(html, wait_until='load')
        page.evaluate('document.fonts.ready')
        page.evaluate("Promise.all(Array.from(document.images).map(i => i.decode().catch(() => {})))")
        page.locator('[data-min-font]').evaluate_all('''elements => {
            for (const element of elements) {
                const minimum = Number(element.dataset.minFont);
                let size = parseInt(getComputedStyle(element).fontSize, 10);
                for (;;) {
                    let style = getComputedStyle(element);
                    if (style.fontFamily.includes('Black Han Sans') && size < 48) {
                        element.style.fontFamily = 'var(--font-body), sans-serif';
                        style = getComputedStyle(element);
                    }
                    if (element.dataset.lines)
                        element.style.maxHeight = Math.ceil(parseFloat(style.lineHeight) * Number(element.dataset.lines)) + "px";
                    if (size <= minimum || (element.scrollHeight <= element.clientHeight + 1 &&
                                            element.scrollWidth <= element.clientWidth + 1)) break;
                    element.style.fontSize = (--size) + "px";
                }
            }
        }''')
        fit_cutout_titles(page)
        page.locator('h1, h2, .headline').evaluate_all('''elements => {
            for (const el of elements) {
                const style = getComputedStyle(el);
                if (style.fontFamily.includes('Black Han Sans') && parseFloat(style.fontSize) < 48)
                    el.style.fontFamily = 'var(--font-body), sans-serif';
            }
        }''')
        fields = page.locator('[data-field]').evaluate_all(
            "els => els.filter(e => e.scrollHeight > e.clientHeight + 1 || e.scrollWidth > e.clientWidth + 1).map(e => e.dataset.field)"
        )
        warnings = ['글이 칸을 넘쳤어요: ' + name for name in dict.fromkeys(fields)]
        if page.evaluate('document.documentElement.scrollHeight > innerHeight + 1'):
            warnings.append('글이 칸을 넘쳤어요: page')
        return RenderResult(page.screenshot(type='png'), warnings)
    finally:
        page.close()


def screenshot(html, metadata, *, browser=None):
    if browser is not None:
        return capture(browser, html, metadata)
    with open_browser() as active:
        return capture(active, html, metadata)


def render_ad_card(profile, menu, copy_text, template=None, theme=None, design=None, *, browser=None):
    design = resolve_theme(profile.business_type, theme, design)
    template = template or design.ad_layout
    menu = menu.model_dump() if hasattr(menu, 'model_dump') else menu
    values = dict(shop_name=profile.shop_name or '', menu_name=menu['name'], price=menu.get('price'),
                  body=copy_text.get('body') or '', photo_url=copy_text.get('photo_url'),
                  cutout_url=copy_text.get('cutout_url'),
                  menu_name_en=copy_text.get('menu_name_en'))
    if getattr(design, 'show_origin', False):
        values['origin'] = copy_text.get('origin') or menu.get('origin') or profile_origin(profile)
    validate_photo(values['cutout_url'])
    warnings = []
    if template == 'big_price' and not (values['price'] or '').strip():
        template = 'cutout_studio' if not cutout_problem(values['cutout_url'], copy_text.get('suggest_original')) else 'photo_full'
    if template == 'cutout_studio':
        problem = cutout_problem(values['cutout_url'], copy_text.get('suggest_original'))
        if problem:
            template = 'photo_full'
            warnings.append(problem)
            values['photo_url'] = values['photo_url'] or values['cutout_url']
    if template in ('receipt', 'big_price') and values['cutout_url']:
        problem = cutout_problem(values['cutout_url'], copy_text.get('suggest_original'))
        if problem:
            values['cutout_url'] = None
            warnings.append(problem)
    for key in ('background_url', 'food_mask_url'):
        values[key] = copy_text.get(key)
    for key in ('photo_url', 'background_url', 'food_mask_url'):
        validate_photo(values[key])
    html, metadata = fill_html('ad_card', values, template=template, theme=theme, business_type=profile.business_type, design=design)
    result = screenshot(html, metadata, browser=browser)
    return RenderResult(result.png, [*warnings, *result.warnings])


def cutout_problem(url, suggest_original=False):
    if not url or suggest_original:
        return '그릇 전체가 나오게 찍어 주세요'
    try:
        with Image.open(BytesIO(base64.b64decode(url.split(',', 1)[1]))) as image:
            if image.mode != 'RGBA':
                return '그릇 전체가 나오게 찍어 주세요'
            mask = image.getchannel('A')
            w, h = mask.size
            edges = [mask.crop(box) for box in ((0, 0, w, 1), (0, h - 1, w, h),
                                                (0, 0, 1, h), (w - 1, 0, w, h))]
            if (any(sum(edge.histogram()[FOREGROUND_MIN_ALPHA:]) >= .05 * max(edge.size) for edge in edges)
                    or analyze_mask(mask)['partial_foreground_ratio'] >= PARTIAL_HINT_RATIO):
                return '그릇 전체가 나오게 찍어 주세요'
    except (ValueError, OSError):
        return '그릇 전체가 나오게 찍어 주세요'
    return None


def profile_origin(profile):
    return ' · '.join(value for value in profile.other_info or []
                      if ORIGIN_PATTERN.search(value))


def validate_photo(photo_url):
    if photo_url and not re.fullmatch(r'data:image/(?:png|jpeg);base64,[A-Za-z0-9+/]+={0,2}', photo_url):
        raise RenderError('사진은 PNG 또는 JPEG 데이터만 사용할 수 있습니다')


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
        row.setdefault('photo_url', None)
        validate_photo(row['photo_url'])
        price = row['price']
        if price and len(price.strip()) <= 16 and re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)', price.strip()):
            row['price'] = f"{int(price.replace(',', '')):,}원"
    footer = [value for value in (profile.hours, profile.closed_days, profile.takeout_delivery) if value]
    return dict(shop_name=profile.shop_name or '', menus=rows, footer=footer,
                intro=' '.join((profile.mood_strengths or '').split()))


def menu_board_layout(template, rows):
    if template == "big_price" and 2 * sum(bool((row.get("price") or "").strip()) for row in rows) < len(rows):
        return "text_list"
    return template


def render_menu_board(profile, menus=None, template=None, theme=None, design=None, *, browser=None):
    design = resolve_theme(profile.business_type, theme, design)
    template = template or design.menu_layout
    values = menu_board_values(profile, menus)
    template = menu_board_layout(template, values["menus"])
    if getattr(design, 'show_origin', False):
        values['origin_note'] = profile_origin(profile)
    else:
        for row in values['menus']:
            row.pop('origin', None)
    values['photo_url'] = next((row['photo_url'] for row in values['menus'] if row['photo_url']), '')
    html, metadata = fill_html('menu_board', values, template=template, theme=theme, business_type=profile.business_type, design=design)
    return screenshot(html, metadata, browser=browser)
