import base64
import json
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.schemas.profile import ShopProfile
from app.services import compose, renderer, template_v3
from app.services.design_options import contrast, default_design
from test_concept import model_candidates
from test_renderer import chromium_available


PROFILE = ShopProfile(shop_name="열두 글자보다 긴 가게 이름입니다", business_type="카페")
CATALOG = template_v3.styles()


def photo_url(touch_edge=False):
    image = Image.new("RGBA", (150, 150))
    ImageDraw.Draw(image).rectangle((0 if touch_edge else 20, 20, 130, 130), fill="brown")
    return "data:image/png;base64," + base64.b64encode(compose.encode_png(image)).decode()


def test_all_palette_and_font_contrasts():
    assert sum(len(item["palettes"]) for item in CATALOG.values()) == 38
    assert sum(len(item["fonts"]) for item in CATALOG.values()) == 18
    for style, item in CATALOG.items():
        for palette, colors in item["palettes"].items():
            assert contrast(colors["ink"], colors["bg"]) >= 7
            assert contrast(colors["sub"], colors["bg"]) >= 4.5
            assert contrast(colors["accent_ink"], colors["accent"]) >= 4.5
            if style != "pop":
                assert contrast(colors["accent"], colors["bg"]) >= 3
            for font in item["fonts"]:
                css = template_v3.context(style, palette, font, "ko")["theme_css"]
                assert all(f"--{key}:" in css for key in ("font-latin", "latin-style", "body-weight", "glyph"))


@pytest.mark.parametrize("field", ["style", "palette", "font", "ad_layout", "menu_layout"])
def test_unknown_model_option_falls_back(api_client, gemini_mock, field):
    rows = model_candidates()
    rows[0]["design"][field] = "unknown"
    gemini_mock.return_value.__enter__.return_value.models.generate_content.return_value.text = json.dumps({"candidates": rows})
    data = api_client.post("/profile/suggest-concept", json={
        "profile": {"shop_name": "가게", "business_type": "일식"},
    }).json()
    assert data["source"] == "기본"
    assert any(item["design"]["style"] == "modern" for item in data["candidates"])
    assert len({c["design"]["style"] for c in data["candidates"]}) == 3


@pytest.fixture(scope="module")
def browser():
    if not chromium_available():
        pytest.skip("Chromium required")
    with renderer.open_browser() as active:
        yield active


@pytest.mark.parametrize("style", list(CATALOG))
@pytest.mark.parametrize("kind,layout", sorted(template_v3.LAYOUTS))
def test_v3_layout_matrix(style, kind, layout, browser):
    design = default_design("카페", style)
    if kind == "ad_card":
        result = renderer.render_ad_card(PROFILE, {"name": "열두글자의정성가득메뉴"}, {
            "photo_url": photo_url(), "cutout_url": photo_url(),
        }, template=layout, design=design, browser=browser)
    else:
        result = renderer.render_menu_board(PROFILE, [{"name": f"메뉴 {i}"} for i in range(12)],
                                            template=layout, design=design, browser=browser)
    with Image.open(BytesIO(result.png)) as image:
        assert image.size == (1080, 1080 if kind == "ad_card" else 1527)


@pytest.mark.parametrize("lang,expected", [("ko", ("라테", None, None)),
                                           ("ko_en", ("라테", "Latte", "en")),
                                           ("en_ko", ("Latte", "라테", "ko"))])
def test_names(lang, expected):
    assert template_v3.names(lang, "라테", "Latte") == expected
    assert template_v3.names(lang, "라테", None) == ("라테", None, None)


@pytest.mark.parametrize("count,columns", [(2, 1), (5, 2), (12, 2)])
def test_premium_columns(count, columns):
    html, _ = renderer.fill_html("menu_board", {
        "shop_name": "가게", "menus": [{"name": str(i)} for i in range(count)],
    }, template="premium")
    assert f'data-cols="{columns}"' in html


def test_origin_and_original_png(monkeypatch):
    captured = []
    monkeypatch.setattr(renderer, "screenshot", lambda html, *args, **kwargs:
                        (captured.append(html), renderer.RenderResult(b"png", []))[1])
    url = photo_url()
    menu = {"name": "라테", "origin": "우유 국내산"}
    design = default_design("카페").model_copy(update={"show_origin": True})
    renderer.render_ad_card(PROFILE, menu, {"cutout_url": url}, template="cutout_studio", design=design)
    renderer.render_ad_card(PROFILE, menu, {"cutout_url": url}, template="cutout_studio")
    assert f'src="{url}"' in captured[0] and f'src="{url}"' in captured[1]
    assert "우유 국내산" in captured[0] and "우유 국내산" not in captured[1]
    assert renderer.cutout_problem(photo_url(touch_edge=True))
    assert renderer.cutout_problem(url) is None


def test_saved_design_precedence_and_rendering_never_recommends(api_client, gemini_mock, monkeypatch):
    saved = default_design('카페', 'grill').model_copy(update={'source': '추천'})
    profile = {'shop_name': '가게', 'business_type': '카페'}
    request = {'profile': profile, 'source_text': '', 'design': saved.model_dump()}
    shop_id = api_client.post('/profile/save', json=request).json()['shop_id']
    request.pop('design')
    assert api_client.post('/profile/save', json={**request, 'shop_id': shop_id}).status_code == 200
    stored = api_client.get(f'/profile/{shop_id}').json()
    assert stored['design'] == saved.model_dump()
    assert 'design' not in stored['profile']
    gemini_mock.reset_mock()  # Saving may infer a concept; rendering must never call the LLM.

    used = []
    def fake(*args):
        used.append(args[-1])
        return renderer.RenderResult(b'png', [])

    monkeypatch.setattr(renderer, 'render_ad_card', fake)
    monkeypatch.setattr(renderer, 'render_menu_board', fake)
    for name in ('라테', '카푸치노'):
        assert api_client.post('/render/ad-card', json={
            'shop_id': shop_id, 'menu': {'name': name}, 'headline': name, 'body': '', 'photo_url': photo_url(),
        }).status_code == 200
    direct = default_design('카페', 'pop').model_dump(exclude={'source', 'reason'})
    assert api_client.post('/render/menu-board', json={'shop_id': shop_id, 'design': direct}).status_code == 200
    assert api_client.post('/render/menu-board', json={'shop_id': shop_id, 'design': {**direct, 'style': 'unknown'}}).status_code == 422
    assert [d.style for d in used] == ['grill', 'grill', 'pop']
    gemini_mock.assert_not_called()


def test_empty_background_retries_dark_edge():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from PIL import ImageDraw
    from app.services.image_models import generate_empty_background
    bad = Image.new('RGB', (100, 100), 'white')
    ImageDraw.Draw(bad).rectangle((0, 0, 10, 99), fill='black')
    model = Mock()
    model.generate.side_effect = [
        SimpleNamespace(png=compose.encode_png(bad)),
        SimpleNamespace(png=compose.encode_png(Image.new('RGB', (100, 100), 'white'))),
    ]
    generate_empty_background(model, None, 42)
    assert [call.args[1] for call in model.generate.call_args_list] == [42, 43]




def test_owner_origins_and_batched_menu_names_are_reused(api_client, monkeypatch):
    from app.services import menu_translation

    translated, rendered = [], []

    def translate(names):
        translated.append(names)
        return {"라테": "Latte", "홍차": "Black Tea"}

    def render(profile, menus, *args):
        rendered.append(menus)
        return renderer.RenderResult(b"png", [])

    monkeypatch.setattr(menu_translation, "translate", translate)
    monkeypatch.setattr(renderer, "render_menu_board", render)
    design = default_design("카페").model_copy(update={"lang": "ko_en", "show_origin": True})
    profile = {**PROFILE.model_dump(), "menus": [{"name": "라테"}, {"name": "홍차"}]}
    saved = api_client.post("/profile/save", json={
        "profile": profile, "source_text": "", "design": design.model_dump(),
        "menu_origins": {"라테": "우유 국내산"},
    })
    assert saved.status_code == 200
    payload = {"shop_id": saved.json()["shop_id"]}
    assert api_client.post("/render/menu-board", json=payload).status_code == 200
    assert api_client.post("/render/menu-board", json=payload).status_code == 200
    assert translated == [["라테", "홍차"]]
    assert rendered[0] == rendered[1]
    assert rendered[0][0]["origin"] == "우유 국내산"
    assert rendered[0][1]["name_en"] == "Black Tea"


@pytest.mark.parametrize("components,expected", [(["연어", "참치"], True), (None, False)])
def test_assorted_menu_prompt_and_component_warning(components, expected):
    from app.schemas.copy import CopyMenu
    from app.services.copy_pipeline import prepare_mode_prompt
    from app.services.fact_check import component_warnings

    menu = CopyMenu(name="모둠 초밥", components=components)
    prompt, contents, _, schema = prepare_mode_prompt(PROFILE, menu, "menu", use_examples=False)
    assert ("구성 나열" in prompt) is expected
    assert ("재료나 구성은 추측하지" in prompt) is not expected
    assert bool(component_warnings(menu, "연어, 참치, 새우")) is expected
    assert ("새우" not in json.loads(contents)["menu"].get("components", []))
    assert "menu_name_en" in schema["properties"]


@pytest.mark.parametrize("layout", ["receipt", "big_price"])
@pytest.mark.parametrize("count", [2, 8, 12])
@pytest.mark.parametrize("footer", [[], ["11:00–21:00", "월요일 휴무"]])
def test_new_menu_board_no_overflow(layout, count, footer, browser):
    html, metadata = renderer.fill_html("menu_board", {
        "shop_name": "우리 가게", "footer": footer,
        "menus": [{"name": f"메뉴 {i}", "price": "180g 17,000원"} for i in range(count)],
    }, template=layout)
    assert renderer.screenshot(html, metadata, browser=browser).warnings == []


def test_shuffled_catalog_is_stable_and_changes_with_shop():
    from app.services.concept_suggester import shuffled_options
    first = shuffled_options(12)
    assert json.dumps(first) == json.dumps(shuffled_options(12))
    assert list(first) != list(shuffled_options(13))
    assert all(value["label"] and value["desc"] for value in first.values())


def test_recommendation_repair_enforces_diversity(monkeypatch):
    from app.services import concept_suggester
    from unittest.mock import Mock
    rows = model_candidates()
    for row in rows:
        row["design"]["ad_layout"] = "photo_full"
    generate = Mock(return_value=json.dumps({"candidates": rows}))
    monkeypatch.setattr(concept_suggester, "generate_json", generate)
    result = concept_suggester.suggest_concepts(PROFILE.model_copy(update={"business_type": "일식"}), "라멘", shop_id=12)
    assert "modern" in {row.design.style for row in result.candidates}
    assert len({row.design.style for row in result.candidates}) == 3
    assert len({row.design.ad_layout for row in result.candidates}) >= 2
    assert all("라멘" in row.design.reason for row in result.candidates)
    generate.assert_called_once()


def test_missing_price_disables_big_price_and_keeps_diversity():
    from app.services.concept_suggester import apply_price_rules, fallback_suggestions

    profile = ShopProfile(shop_name="가게", business_type="카페",
                          menus=[{"name": "라테"}, {"name": "홍차"}, {"name": "케이크", "price": "5000원"}])
    result = fallback_suggestions(profile, "라테")
    for row in result.candidates:
        row.design.ad_layout = "big_price"
        row.design.menu_layout = "big_price"
    apply_price_rules(result.candidates, profile, "라테", True)
    assert {row.design.ad_layout for row in result.candidates} == {"photo_full", "receipt"}
    assert {row.design.menu_layout for row in result.candidates} == {"text_list"}


@pytest.mark.parametrize("layout", ["text_list", "premium", "receipt", "big_price"])
@pytest.mark.parametrize("count", [2, 3])
def test_short_menu_board_grows_without_overflow(layout, count, browser):
    result = renderer.render_menu_board(PROFILE.model_copy(update={"shop_name": "우리 가게"}), [{"name": f"메뉴 {i}", "price": "4,000원"} for i in range(count)],
                                        template=layout, browser=browser)
    assert not result.warnings


def test_receipt_accepts_80_character_body(browser):
    body = "담백한 맛과 부드러운 식감을 느껴 보세요. " * 4
    result = renderer.render_ad_card(PROFILE, {"name": "라테", "price": "4,000원"},
                                    {"body": body[:80], "photo_url": photo_url()},
                                    template="receipt", browser=browser)
    assert not result.warnings



def test_modern_cutout_body_does_not_overlap_price(browser):
    body = "숯불 향이 은은한 양념갈비 한 점. 달짝지근한 양념과 고소한 육즙이 어우러져 한 입이 든든해요. 잘 어울려요. 한 접시로 천천히 즐겨 보세요."
    body = body[:60]
    assert len(body) == 60
    html, metadata = renderer.fill_html("ad_card", {
        "shop_name": "참숯마루", "menu_name": "양념갈비", "price": "300g 19,000원",
        "body": body, "cutout_url": photo_url(),
    }, template="cutout_studio", design=default_design("일식", "modern"))
    page = browser.new_page(viewport=metadata["size"])
    try:
        page.route("https://render.invalid/fonts/*", lambda route: route.fulfill(
            path=renderer.TEMPLATES / "fonts" / route.request.url.rsplit("/", 1)[-1], content_type="font/ttf",
        ))
        page.set_content(html.replace("<head>", '<head><base href="https://render.invalid/out/">'))
        page.wait_for_selector("body[data-ready]")
        price = page.locator('[data-field="price"]')
        copy = page.locator('[data-field="body"]')
        assert price.inner_text() == "300g 19,000원"
        assert copy.inner_text() == body
        price_rect, copy_rect = price.bounding_box(), copy.bounding_box()
        assert price_rect and copy_rect
        assert min(price_rect["x"] + price_rect["width"], copy_rect["x"] + copy_rect["width"]) <= max(price_rect["x"], copy_rect["x"]) or min(
            price_rect["y"] + price_rect["height"], copy_rect["y"] + copy_rect["height"]
        ) <= max(price_rect["y"], copy_rect["y"])
    finally:
        page.close()
