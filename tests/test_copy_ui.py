from streamlit.testing.v1 import AppTest

from app.core import config
from app.ui import api_client
from eval.common import ROOT


def test_copy_tab_renders_channels_warnings_and_preserves_result(monkeypatch):
    seen = []
    monkeypatch.setattr(config, "GEMINI_TIMEOUT_MS", 300_000)

    def fake_api(base, method, path, *, payload=None, **kwargs):
        if path == "/profile/list":
            return [{"id": 7, "shop_name": "가게", "business_type": "카페", "updated_at": "now"}]
        assert path == "/copy/generate"
        assert kwargs["timeout"] == 320
        seen.append(payload)
        return {"instagram": {"body": "첫 줄\n둘째 줄\n셋째 줄", "hashtags": ["#메뉴"]},
                "delivery_app": {"body": "배달 문구"}, "naver_place": {"body": "플레이스 문구"},
                "warnings": ["피할 표현 '강추'이 들어갔어요"]}

    monkeypatch.setattr(api_client, "request_api", fake_api)
    view = AppTest.from_file(str(ROOT / "app/ui/main_ui.py"), default_timeout=30).run()
    assert [tab.label for tab in view.tabs] == ["가게 프로필", "문구 만들기"]
    view.selectbox(key="copy_shop_id").select(7).run()
    view.text_input(key="copy_menu_name").input(" 라떼 ")
    view.text_area(key="copy_menu_this_time").input("이번 주만 1,000원 할인")
    next(item for item in view.button if item.label == "문구 만들기").click().run()
    assert not view.exception
    assert seen[0] == {"shop_id": 7, "menu": {"name": "라떼", "price": None, "features": None, "this_time": "이번 주만 1,000원 할인"}}
    assert any("피할 표현" in item.value for item in view.warning)
    assert any(item.value == "배달 문구" for item in view.text)
    view.run()
    assert any(item.value == "배달 문구" for item in view.text)
    view.text_input(key="copy_menu_name").input("다른 메뉴").run()
    assert not any(item.value == "배달 문구" for item in view.text)
