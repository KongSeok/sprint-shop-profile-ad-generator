import streamlit as st

from app.ui.render_tab import render_ad_controls
from app.core.config import GEMINI_TIMEOUT_MS
from app.ui.api_client import UserApiError
from app.ui.profile_form import blank_to_none


def clear_copy_result():
    st.session_state.pop("copy_result", None)
    st.session_state.pop("ad_png", None)
    st.session_state.pop("ad_headline", None)
    st.session_state.pop("ad_body", None)


def render_copy_tab(api, shops):
    st.header("문구 만들기")
    choices = {shop["id"]: shop for shop in shops}
    selected = st.selectbox(
        "문구를 만들 가게", [None, *choices], key="copy_shop_id",
        format_func=lambda value: "가게를 선택하세요" if value is None else f"{choices[value]['shop_name']} (#{value})",
        on_change=clear_copy_result,
    )
    if not shops:
        st.info("먼저 가게 프로필을 저장해 주세요. 저장 후 목록을 새로 불러오면 선택할 수 있어요")
    name = st.text_input("메뉴명 (필수)", key="copy_menu_name", on_change=clear_copy_result)
    price = st.text_input("가격", key="copy_menu_price", on_change=clear_copy_result)
    features = st.text_area("메뉴 특징", key="copy_menu_features", on_change=clear_copy_result)
    this_time = st.text_area("이번만 요청", placeholder="예: 이번 주만 1,000원 할인", key="copy_menu_this_time", on_change=clear_copy_result)
    if st.button("문구 만들기", type="primary", disabled=selected is None):
        if not name.strip():
            st.error("메뉴 이름을 적어 주세요")
        else:
            try:
                with st.spinner("채널별 문구를 만들고 있어요…"):
                    st.session_state.copy_result = api("POST", "/copy/generate", payload={
                        "shop_id": selected,
                        "menu": {"name": name.strip(), "price": blank_to_none(price),
                                 "features": blank_to_none(features), "this_time": blank_to_none(this_time)},
                    }, timeout=GEMINI_TIMEOUT_MS / 1000 + 20)
            except UserApiError as exc:
                st.error(str(exc))
    result = st.session_state.get("copy_result")
    if result:
        for warning in result.get("warnings", []):
            st.warning(warning)
        for field, title in (("instagram", "인스타그램"), ("delivery_app", "배달앱"), ("naver_place", "네이버 플레이스")):
            st.subheader(title)
            st.text(result[field]["body"])
            if field == "instagram":
                st.text(" ".join(result[field]["hashtags"]))

        render_ad_controls(api, selected, {"name": name.strip(), "price": blank_to_none(price), "features": blank_to_none(features), "this_time": blank_to_none(this_time)}, result)
