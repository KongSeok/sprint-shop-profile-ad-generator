from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from app.schemas.profile import ShopProfile
from app.ui import api_client
from eval.common import ROOT


def button(view, label):
    return next(item for item in view.button if item.label == label)


def test_ui_extract_edit_rerun_save_reload_update(monkeypatch):
    shops = {}
    extracted = ShopProfile(shop_name=None, business_type="카페", needs_check=["휴무일 확인 필요"]).model_dump()

    def fake_api(base, method, path, *, payload=None, **kwargs):
        if path == "/profile/list":
            return [{"id": key, "shop_name": row["profile"]["shop_name"], "business_type": "카페", "updated_at": "now"} for key, row in shops.items()]
        if path == "/profile/extract":
            assert payload["prompt_version"] == "v2"
            return extracted
        if path == "/profile/save":
            shop_id = payload["shop_id"] or len(shops) + 1
            shops[shop_id] = {**payload, "shop_id": shop_id}
            return {"shop_id": shop_id}
        return shops[int(path.rsplit("/", 1)[1])]

    monkeypatch.setattr(api_client, "request_api", fake_api)
    view = AppTest.from_file(str(ROOT / "app/ui/main_ui.py"), default_timeout=30).run()
    view.text_area(key="source_input").input("월요일 휴무이고 연중무휴예요")
    button(view, "정리하기").click().run()
    assert not view.exception
    assert "서로 다른 내용" in view.warning[0].value
    view.text_input(key="draft_1_shop_name").input(" 우리 가게 ").run()
    view.run()  # Repeated reruns retain unsaved edits.
    assert view.text_input(key="draft_1_shop_name").value == " 우리 가게 "
    button(view, "저장").click().run()
    assert not view.exception and len(shops) == 1
    assert shops[1]["profile"]["shop_name"] == "우리 가게"
    assert "저장했어요" in view.success[0].value
    view.selectbox(key="saved_selection").select(1).run()
    button(view, "불러오기").click().run()
    assert not view.exception
    view.text_input(key="draft_2_shop_name").input("수정 가게").run()
    button(view, "저장").click().run()
    assert not view.exception and len(shops) == 1
    assert shops[1]["profile"]["shop_name"] == "수정 가게"


def test_api_errors_do_not_show_internal_messages_or_keys(monkeypatch):
    response = Mock(ok=False, status_code=502)
    response.json.return_value = {"detail": {"code": "GEMINI_CALL_FAILED", "message": "SECRET_INTERNAL_API_KEY"}}
    monkeypatch.setattr(api_client.requests, "request", Mock(return_value=response))
    with pytest.raises(api_client.UserApiError) as caught:
        api_client.request_api("http://localhost", "POST", "/profile/extract")
    assert "잠시 후 다시 눌러 주세요" in str(caught.value)
    assert "SECRET_INTERNAL_API_KEY" not in str(caught.value)
