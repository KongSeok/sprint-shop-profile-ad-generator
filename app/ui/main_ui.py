import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.ui.api_client import UserApiError
from app.ui.copy_tab import render_copy_page
from app.ui.labels import shop_label
from app.ui.profile_page import render_profile_page
from app.ui.quick_page import render_quick_page
from app.ui.render_tab import render_ad_page, render_menu_page
from app.ui.state import api, clear_results, set_draft
from app.ui.theme import render_theme


st.set_page_config(page_title="우리 가게 광고 만들기", page_icon="🍽️", layout="wide")
profile = st.Page(lambda: render_profile_page(copy), title="가게 정보", icon="🏪", url_path="profile")
copy = st.Page(lambda: render_copy_page(ad), title="문구 만들기", icon="✍️", url_path="copy")
ad = st.Page(render_ad_page, title="광고 카드", icon="🖼️", url_path="ad")
board = st.Page(render_menu_page, title="메뉴판", icon="📋", url_path="board")
quick = st.Page(lambda: render_quick_page(profile, copy, ad), title="✨ 한 번에 만들기", default=True)
pages = (quick, profile, copy, ad, board)
current = st.navigation(pages, position="hidden")
render_theme()


def reset_inputs():
    state = st.session_state
    state.source_revision = state.get("source_revision", 0) + 1
    for key in state.pop("page_inputs", {}):
        state.pop(key, None)
    for key in ("menu_selection", "copy_menu_selection", "ad_menu_selection"):
        state.pop(key, None)


def select_shop():
    state = st.session_state
    selected = state.saved_selection
    if selected == state.get("shop_id"):
        return
    try:
        if selected is None:
            set_draft({}, "")
            state.pop("draft", None)
            state.pop("saved_profile", None)
            state.pop("saved_shop", None)
        else:
            saved = api("GET", f"/profile/{selected}")
            state.saved_shop = {**saved, "shop_id": selected}
            state.saved_profile = saved["profile"]
            set_draft(saved["profile"], saved["source_text"], selected, saved["prompt_version"],
                      saved.get("concept"), saved.get("design"), saved.get("menu_origins"))
        clear_results()
        state.pop("quick_results", None)
        state.pop("quick_pending", None)
        reset_inputs()
        state.pop("design_notice", None)
        state.pop("shop_load_error", None)
    except UserApiError as exc:
        state.shop_load_error = str(exc)
        state.saved_selection = state.get("shop_id")


def new_shop():
    already_new = st.session_state.get("shop_id") is None
    st.session_state.saved_selection = None
    select_shop()
    if already_new:
        st.session_state.pop("draft", None)
        reset_inputs()


with st.sidebar:
    st.markdown('<div class="shop-app-name">우리 가게 광고 만들기</div>', unsafe_allow_html=True)
    st.caption("사진과 가격만 넣으면 광고가 나와요")
    state = st.session_state
    if "shops" not in state or state.pop("reload_shops", False):
        try:
            state.shops = api("GET", "/profile/list")
            state.pop("list_error", None)
        except UserApiError as exc:
            state.setdefault("shops", [])
            state.list_error = str(exc)
    if state.get("sync_saved_selection"):
        state.saved_selection = state.shop_id
        state.pop("sync_saved_selection")
    choices = {shop["id"]: shop for shop in state.shops}
    st.selectbox("가게 선택", [None, *choices], key="saved_selection",
                 format_func=lambda value: shop_label(choices[value]) if value in choices else "가게를 선택하세요",
                 on_change=select_shop)
    if st.button("＋ 새 가게", on_click=new_shop):
        st.switch_page(profile)
    if error := state.get("shop_load_error") or state.get("list_error"):
        st.warning(error)
    st.divider()
    st.page_link(quick, label=quick.title)
    st.caption("직접 고치기")
    for page, key in zip(pages[1:], ("shop_id", "copy_result", "ad_png", "board_png")):
        with st.container(key=f"nav_{key}_{'current' if page is current else 'link'}"):
            st.page_link(page, label=page.title + (" ✓" if state.get(key) else ""),
                         icon=page.icon, disabled=page is not profile and not state.get("shop_id"))
    st.divider()
    if st.button("목록 새로 불러오기"):
        state.reload_shops = True
        st.rerun()

if current not in (profile, quick) and not state.get("shop_id"):
    st.switch_page(profile)
if current is not profile and state.get("saved_profile") and (
    state.get("draft_invalid") or state.get("draft") != state.saved_profile
    or state.get("draft_origins", {}) != (state.get("saved_shop", {}).get("menu_origins") or {})
):
    st.warning("가게 정보에 저장 안 한 내용이 있어요")
    st.page_link(profile, label="저장하러 가기")
current.run()
