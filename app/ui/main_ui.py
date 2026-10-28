import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.core.config import API_BASE_URL, GEMINI_TIMEOUT_MS
from app.ui.api_client import UserApiError, request_api
from app.ui.concept_panel import render_concept_panel, selected_concept
from app.ui.copy_tab import render_copy_tab
from app.ui.profile_form import LIST_FIELDS, TEXT_FIELDS, form_to_profile, list_to_lines

st.set_page_config(page_title="가게 프로필", page_icon="🏪")


def clear_saved_notice():
    st.session_state.pop("saved_notice", None)


def set_draft(profile, source_text, shop_id=None, version="v2", concept=None):
    st.session_state.draft_concept = concept
    st.session_state.draft = profile
    st.session_state.draft_source = source_text
    st.session_state.shop_id = shop_id
    st.session_state.prompt_version = version
    st.session_state.draft_revision = st.session_state.get("draft_revision", 0) + 1
    clear_saved_notice()


def api(method, path, **kwargs):
    return request_api(API_BASE_URL, method, path, **kwargs)


with st.sidebar:
    st.header("저장된 가게")
    if st.button("목록 새로 불러오기"):
        st.session_state.reload_shops = True
    if "shops" not in st.session_state or st.session_state.get("reload_shops"):
        try:
            st.session_state.shops = api("GET", "/profile/list")
            st.session_state.reload_shops = False
            st.session_state.pop("list_error", None)
        except UserApiError as exc:
            st.session_state.shops = []
            st.session_state.list_error = str(exc)
    if st.session_state.get("list_error"):
        st.warning(st.session_state.list_error)
    choices = {shop["id"]: shop for shop in st.session_state.shops}
    selected = st.selectbox(
        "가게 선택", [None, *choices],
        format_func=lambda value: "가게를 선택하세요" if value is None else f"{choices[value]['shop_name']} · {choices[value]['business_type']} (#{value})",
        key="saved_selection",
    )
    if st.button("불러오기", disabled=selected is None):
        try:
            saved = api("GET", f"/profile/{selected}")
            set_draft(saved["profile"], saved["source_text"], saved["shop_id"], saved["prompt_version"], saved.get("concept"))
            st.session_state.source_input = saved["source_text"]
        except UserApiError as exc:
            st.error(str(exc))
    if st.button("새 가게 작성"):
        st.session_state.pop("draft", None)
        st.session_state.shop_id = None
        st.session_state.source_input = ""
        clear_saved_notice()

profile_tab, copy_tab = st.tabs(["가게 프로필", "문구 만들기"])
with profile_tab:
    st.title("가게 프로필 만들기")
    if st.session_state.get("saved_notice"):
        st.success(f"저장했어요 · 저장 번호 {st.session_state.saved_notice}")

    st.subheader("1. 가게 소개")
    source = st.text_area("가게 소개를 편하게 적어 주세요", height=200, key="source_input", on_change=clear_saved_notice)
    if st.button("정리하기", type="primary"):
        if not source.strip():
            st.info("가게 소개를 먼저 적어 주세요")
        else:
            try:
                with st.spinner("가게 소개를 정리하고 있어요…"):
                    extracted = api("POST", "/profile/extract", payload={"text": source, "prompt_version": "v2"}, timeout=GEMINI_TIMEOUT_MS / 1000 + 20)
                set_draft(extracted, source, st.session_state.get("shop_id"))
            except UserApiError as exc:
                st.error(str(exc))

    if "draft" in st.session_state:
        draft = st.session_state.draft
        revision = st.session_state.draft_revision
        st.subheader("2. 이렇게 이해했어요")
        if draft.get("needs_check"):
            st.warning("글에서 서로 다른 내용이 있어요. 확인해 주세요")
            for item in draft["needs_check"]:
                st.write(f"• {item}")
        st.caption("비어 있는 칸은 글에 없었어요. 필요한 내용만 채워 주세요")
        values = {}
        for field, label in TEXT_FIELDS.items():
            key = f"draft_{revision}_{field}"
            if key not in st.session_state:
                st.session_state[key] = draft.get(field) or ""
            values[field] = st.text_input(label, key=key, placeholder="글에 없었어요", on_change=clear_saved_notice)
        st.write("대표 메뉴·가격")
        frame = pd.DataFrame(draft.get("menus") or [], columns=["name", "price"]).fillna("").astype(str)
        menu_rows = st.data_editor(
            frame, num_rows="dynamic", hide_index=True, key=f"draft_{revision}_menus",
            column_config={"name": st.column_config.TextColumn("메뉴 이름"), "price": st.column_config.TextColumn("가격")},
            on_change=clear_saved_notice,
        )
        for field, label in LIST_FIELDS.items():
            key = f"draft_{revision}_{field}"
            if key not in st.session_state:
                st.session_state[key] = list_to_lines(draft.get(field))
            values[field] = st.text_area(f"{label} (한 줄에 하나씩)", key=key, placeholder="글에 없었어요", on_change=clear_saved_notice)
        concept_panel = render_concept_panel(api, values, menu_rows, draft, revision)
        st.subheader("3. 저장")
        if st.button("저장", type="primary"):
            try:
                profile = form_to_profile(values, menu_rows, draft.get("needs_check"))
                if not profile["shop_name"] or not profile["business_type"]:
                    st.error("가게 이름과 업종은 꼭 적어 주세요")
                else:
                    concept = selected_concept(concept_panel)
                    result = api("POST", "/profile/save", payload={
                        "shop_id": st.session_state.get("shop_id"), "profile": profile,
                        "source_text": st.session_state.draft_source,
                        "prompt_version": st.session_state.prompt_version,
                        "concept": concept,
                    })
                    st.session_state.draft_concept = concept
                    st.session_state.shop_id = result["shop_id"]
                    st.session_state.saved_notice = result["shop_id"]
                    st.session_state.reload_shops = True
                    st.rerun()
            except (UserApiError, ValueError) as exc:
                st.error(str(exc))

with copy_tab:
    render_copy_tab(api, st.session_state.shops)
