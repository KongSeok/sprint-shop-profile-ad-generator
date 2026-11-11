import json
from unittest.mock import Mock

import pytest

from app.core import config
from app.schemas.concept import Concept
from app.schemas.copy import CopyMenu
from app.schemas.profile import ShopProfile
from app.services import concept_suggester, shop_store
from app.services.copy_pipeline import prepare_mode_prompt
from app.services.llm_client import LLMError
from app.ui.concept_form import concept_from_form


CANDIDATE = dict(name="동네 쉼표", mood="편안한 동네 분위기", tone="짧고 친근한 해요체", theme="카페")
AUTO = {**CANDIDATE, "source": "자동"}
PROFILE = ShopProfile(shop_name="동네 가게", business_type="카페",
                      menus=[dict(name="라테", price="4000원")])
PAYLOAD = dict(profile=PROFILE.model_dump(), prompt_version="v2", source_text="동네 가게예요. 라테 한 잔 쉬었다 가세요.")


@pytest.fixture
def auto_llm(monkeypatch):
    call = Mock(return_value=json.dumps(CANDIDATE, ensure_ascii=False))
    monkeypatch.setattr(concept_suggester, "generate_json", call)
    return call


def save(api_client, **overrides):
    response = api_client.post("/profile/save", json={**PAYLOAD, **overrides})
    assert response.status_code == 200, response.text
    return response.json()


def test_save_auto_returns_persisted_concept(api_client, auto_llm):
    result = save(api_client)
    assert result["concept"] == AUTO
    saved = api_client.get(f"/profile/{result['shop_id']}").json()
    assert saved["concept"] == AUTO
    assert "concept" not in saved["profile"]
    auto_llm.assert_called_once()


@pytest.mark.parametrize("field", ["tone", "mood_strengths"])
def test_profile_preference_skips_auto(api_client, auto_llm, field):
    result = save(api_client, profile={**PAYLOAD["profile"], field: "사장님이 적은 말"})
    assert result["concept"] is None
    auto_llm.assert_not_called()


@pytest.mark.parametrize("source", ["직접", "추천"])
def test_owner_selection_skips_auto(api_client, auto_llm, source):
    selected = {**CANDIDATE, "source": source}
    assert save(api_client, concept=selected)["concept"] == selected
    auto_llm.assert_not_called()


@pytest.mark.parametrize("failure", ["llm", "json", "validation"])
def test_auto_failure_keeps_save_available(api_client, auto_llm, caplog, failure):
    if failure == "llm":
        auto_llm.side_effect = LLMError("TEST_ERROR", "PRIVATE_KEY_MUST_NOT_APPEAR")
    else:
        auto_llm.return_value = "not json" if failure == "json" else "{}"
    result = save(api_client)
    assert result["concept"] is None
    assert api_client.get(f"/profile/{result['shop_id']}").status_code == 200
    assert "Automatic concept unavailable" in caplog.text
    assert "PRIVATE_KEY_MUST_NOT_APPEAR" not in caplog.text


def test_same_source_reuses_auto_changed_source_regenerates(api_client, auto_llm):
    result = save(api_client)
    assert save(api_client, shop_id=result["shop_id"], concept=None)["concept"] == AUTO
    assert auto_llm.call_count == 1
    auto_llm.return_value = json.dumps({**CANDIDATE, "name": "새 쉼표"})
    changed = save(api_client, shop_id=result["shop_id"], source_text="원문이 바뀌었어요", concept=None)
    assert changed["concept"]["name"] == "새 쉼표"
    assert auto_llm.call_count == 2


def test_auto_inputs_and_theme(auto_llm):
    profile = PROFILE.model_copy(update=dict(
        owner_phrases=["한 잔 쉬었다 가세요"], avoid_expressions=["최고"],
        other_info=["예약 문의"], location="모델에 별도 전달하지 않을 위치"))
    generated = concept_suggester.auto_concept(profile, "사장님 원문")
    assert generated.source == "자동"
    prompt, contents, schema, temperature, task = auto_llm.call_args.args
    data = json.loads(contents)
    assert set(data) == {"source_text", "shop_name", "business_type", "menus",
                         "owner_phrases", "avoid_expressions", "other_info"}
    assert data["source_text"] == "사장님 원문"
    assert data["menus"] == [{"name": "라테", "price": "4000원"}]
    assert temperature == 0.3 and task == "concept_auto"
    assert "source" not in schema["properties"]
    assert all(theme in prompt for theme in concept_suggester.allowed_themes())
    auto_llm.return_value = json.dumps({**CANDIDATE, "theme": "없는테마"})
    assert concept_suggester.auto_concept(profile, "원문").theme == "기본"


@pytest.mark.parametrize("mode", ["shop", "menu"])
def test_both_copy_modes_use_auto_tone_and_profile_wins(mode):
    menu = CopyMenu(name="라테") if mode == "menu" else None
    prompt, contents, _, _ = prepare_mode_prompt(
        PROFILE, menu, mode, concept=AUTO, use_examples=False)
    assert json.loads(contents)["concept"] == {"mood": AUTO["mood"], "tone": AUTO["tone"]}
    assert "사장님이 고른 컨셉. 사실이 아니니 사실처럼 쓰지 않기" in prompt
    _, contents, _, _ = prepare_mode_prompt(
        PROFILE.model_copy(update={"tone": "정중하게"}), menu, mode, concept=AUTO, use_examples=False)
    assert "concept" not in json.loads(contents)


def test_design_request_receives_saved_auto_direction(api_client, auto_llm):
    result = save(api_client)
    auto_llm.reset_mock()
    # Invalid design output is repaired using the existing fallback rules.
    response = api_client.post("/profile/suggest-concept", json={"shop_id": result["shop_id"]})
    assert response.status_code == 200
    prompt, contents, _, _, task = auto_llm.call_args.args
    assert task == "concept_design"
    assert json.loads(contents)["concept"] == {"mood": AUTO["mood"], "tone": AUTO["tone"]}
    assert "사장님이 고른 컨셉. 사실이 아니니 사실처럼 쓰지 않기" in prompt


def test_auto_edited_by_owner_becomes_direct():
    assert concept_from_form(CANDIDATE, AUTO)["source"] == "자동"
    assert concept_from_form({**CANDIDATE, "tone": "정중한 해요체"}, AUTO)["source"] == "직접"


def test_quick_initial_save_and_design_preserve_auto(api_client, auto_llm, monkeypatch):
    from app.ui import state, quick_page
    from app.services.design_options import default_design
    from app.services.gemini_retry import request_timeout_seconds

    class State(dict):
        __getattr__ = dict.__getitem__
        __setattr__ = dict.__setitem__

    session = State()
    monkeypatch.setattr(state.st, "session_state", session)
    saves = []

    def save_api(method, path, *, payload, timeout):
        assert path == "/profile/save"
        assert timeout == request_timeout_seconds(config.GEMINI_TIMEOUT_MS)
        saves.append(payload)
        response = api_client.post(path, json=payload)
        assert response.status_code == 200
        return response.json()

    monkeypatch.setattr(state, "api", save_api)
    state.save_shop(PAYLOAD)
    state.set_draft(PAYLOAD["profile"], PAYLOAD["source_text"], session.shop_id,
                    concept=session.saved_shop["concept"])
    assert session.draft_concept == AUTO

    def quick_api(method, path, *, payload, **kwargs):
        if path == "/copy/generate":
            assert payload["shop_id"] == session.shop_id
            return {"mode": payload["mode"]}
        if path == "/image/cutout":
            return dict(original_png_base64="original", cutout_png_base64="cutout", suggest_original=False)
        if path == "/profile/suggest-concept":
            return {"candidates": [{"design": default_design("카페").model_dump()}]}
        return {"png_base64": "board"}

    monkeypatch.setattr(quick_page, "api", quick_api)
    monkeypatch.setattr(quick_page, "build_ad", lambda *args: "ad")
    result = quick_page.generate_quick(session.saved_shop, [({"name": "라테"}, b"photo")], lambda _: None)
    assert result["design_saved"] and not result["errors"]
    assert len(saves) == 2 and saves[1]["concept"] == AUTO
    assert session.saved_shop["concept"] == session.draft_concept == AUTO
    assert api_client.get(f"/profile/{session.shop_id}").json()["concept"] == AUTO
    auto_llm.assert_called_once()


def test_automatic_concept_labels_and_owner_edit():
    from streamlit.testing.v1 import AppTest

    script = """
import streamlit as st
from app.ui.concept_panel import render_concept_panel, selected_concept
st.session_state.setdefault("draft_concept", {
    "name": "동네 쉼표", "mood": "편안한 분위기", "tone": "친근한 해요체", "theme": "카페", "source": "자동"})
panel = render_concept_panel(None, {}, [], {}, 1)
st.session_state["selected_for_save"] = selected_concept(panel)
"""
    view = AppTest.from_string(script, default_timeout=30).run()
    assert not view.exception
    assert "자동으로 정하기" in view.radio[0].options
    assert "저장된 컨셉 (자동)" in view.radio[0].options
    assert any("고르지 않으면 가게 소개 글을 읽고 자동으로 정해요" in item.value for item in view.caption)
    assert view.session_state["selected_for_save"]["source"] == "자동"
    view.text_input(key="concept_1_0_saved_tone").input("새로 적은 말투").run()
    assert not view.exception
    assert view.session_state["selected_for_save"]["source"] == "직접"
