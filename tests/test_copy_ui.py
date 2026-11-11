from streamlit.testing.v1 import AppTest

from app.core import config
from app.ui import api_client
from eval.common import ROOT
from ui_navigation import navigate


def test_copy_tab_renders_channels_warnings_and_preserves_result(monkeypatch):
    seen = []
    monkeypatch.setattr(config, "GEMINI_TIMEOUT_MS", 300_000)

    def fake_api(base, method, path, *, payload=None, **kwargs):
        if path == "/profile/list":
            return [{"id": 7, "shop_name": "가게", "business_type": "카페", "updated_at": "now"}]
        if path == "/profile/7":
            return {"profile": {"shop_name": "가게", "business_type": "카페", "menus": [{"name": "라떼", "price": "4000원"}]},
                    "source_text": "", "prompt_version": "v2"}
        assert path == "/copy/generate"
        assert kwargs["timeout"] == 1860
        seen.append(payload)
        return {"instagram": {"body": "첫 줄\n둘째 줄\n셋째 줄", "hashtags": ["#메뉴"]},
                "delivery_app": {"menu_description": "배달 문구"}, "naver_place": {"body": "플레이스 문구"},
                "warnings": ["피할 표현 '강추'이 들어갔어요"]}

    monkeypatch.setattr(api_client, "request_api", fake_api)
    view = AppTest.from_file(str(ROOT / "app/ui/main_ui.py"), default_timeout=30).run()
    view.selectbox(key="saved_selection").select(7).run()
    navigate(view, "copy")
    assert view.text_input(key="copy_menu_price").value == "4000원"
    assert any(item.label == "가게 소개 문구" for item in view.button)
    view.text_input(key="copy_menu_name").input(" 라떼 ")
    view.text_area(key="copy_menu_this_time").input("이번 주만 1,000원 할인")
    next(item for item in view.button if item.label == "메뉴 문구 만들기").click().run()
    assert not view.exception
    assert seen[0] == {"mode": "menu", "shop_id": 7, "menu": {"name": "라떼", "price": "4000원", "features": None, "this_time": "이번 주만 1,000원 할인"}}
    assert [tab.label for tab in view.tabs] == ["인스타그램", "배달앱", "네이버 플레이스"]
    assert any(item.label == "확인해 볼 점 (1개)" for item in view.expander)
    assert any(item.value == "배달 문구" for item in view.get("code"))
    view.run()
    assert any(item.value == "배달 문구" for item in view.get("code"))
    view.text_input(key="copy_menu_name").input("다른 메뉴").run()
    assert not any(item.value == "배달 문구" for item in view.get("code"))


def test_uploaded_photo_design_previews_and_design_only_save(monkeypatch):
    from base64 import b64encode
    from io import BytesIO

    from PIL import Image, ImageDraw

    from app.services.design_options import default_design

    png = BytesIO()
    image = Image.new("RGBA", (64, 64))
    ImageDraw.Draw(image).ellipse((12, 12, 52, 52), fill="orange")
    image.save(png, format="PNG")
    encoded = b64encode(png.getvalue()).decode()
    saved = {
        "shop_id": 7,
        "profile": {"shop_name": "온기 커피", "business_type": "카페",
                    "menus": [{"name": "라떼", "price": "4000원"}]},
        "source_text": "라떼를 판매하는 카페",
        "prompt_version": "v1",
        "concept": {"name": "온기", "mood": "포근한", "tone": "차분한", "theme": "기본"},
        "menu_origins": {"라떼": "우유 국내산"},
        "design": default_design("카페").model_dump(),
    }
    candidates = [
        {"design": default_design("카페", style).model_dump(exclude={"lang", "show_origin", "source"})}
        for style in ("cozy", "modern", "classic")
    ]
    candidates[0]["design"]["ad_layout"] = "cutout_studio"
    previews, saves, ad_designs = [], [], []

    def fake_api(base, method, path, *, payload=None, **kwargs):
        if path == "/profile/list":
            return [{"id": 7, "shop_name": "온기 커피", "business_type": "카페"}]
        if path == "/profile/7":
            return saved.copy()
        if path == "/image/cutout":
            return {"original_png_base64": encoded, "cutout_png_base64": encoded, "suggest_original": False}
        if path == "/profile/suggest-concept":
            assert payload["shop_id"] == 7 and "profile" not in payload
            assert payload["photo_menu_count"] == 1
            return {"source": "추천", "candidates": candidates}
        if path == "/profile/save":
            saves.append(payload)
            saved["design"] = payload["design"]
            return {"shop_id": 7}
        if path == "/image/compose":
            return {"composite_png_base64": encoded}
        assert path == "/render/ad-card"
        if "profile" in payload:
            assert payload["photo_url"].startswith("data:image/jpeg;base64,")
            assert payload["cutout_url"] == "data:image/png;base64," + encoded
            previews.append(payload)
        else:
            ad_designs.append(saved["design"])
        return {"png_base64": encoded, "warnings": []}

    monkeypatch.setattr(api_client, "request_api", fake_api)
    view = AppTest.from_file(str(ROOT / "app/ui/main_ui.py"), default_timeout=30).run()
    view.selectbox(key="saved_selection").select(7).run()
    navigate(view, "ad")
    view.file_uploader[0].upload("latte.png", png.getvalue(), "image/png").run()
    assert not view.exception
    assert len(previews) == 3
    assert len(view.image) == 5  # Three candidates and two photo previews.
    assert any("후보 1 · 포근한 · 음식만 크게" in item.value for item in view.markdown)
    next(item for item in view.radio if item.label == "배경 합성에 사용할 사진").set_value("original").run()
    navigate(view, "copy")
    navigate(view, "ad")
    assert len(view.image) == 5
    assert next(item for item in view.radio if item.label == "배경 합성에 사용할 사진").value == "original"
    for candidate in (0, 1):
        [item for item in view.button if item.label == "이걸로"][candidate].click().run()
        assert not view.exception
    assert len(saves) == 2
    expected = {field: value for field, value in saved.items() if field != "design"}
    assert [{field: value for field, value in payload.items() if field != "design"}
            for payload in saves] == [expected, expected]
    assert [payload["design"]["style"] for payload in saves] == ["cozy", "modern"]
    next(item for item in view.button if item.label == "광고 카드 만들기").click().run()
    assert not view.exception
    assert ad_designs == [saves[-1]["design"]]
