import streamlit as st

from app.core.config import GEMINI_TIMEOUT_MS
from app.ui.api_client import UserApiError
from app.ui.profile_form import blank_to_none
from app.ui.render_tab import render_ad_controls


def clear_copy_result():
    for key in ("copy_result", "ad_png", "ad_headline", "ad_body"):
        st.session_state.pop(key, None)


def render_copy_tab(api, shops):
    st.header("문구 만들기")
    st.caption("가게 프로필을 먼저 저장한 뒤, 소개 문구 또는 메뉴 문구를 골라 주세요")
    choices = {shop["id"]: shop for shop in shops}
    selected = st.selectbox("문구를 만들 가게", [None, *choices], key="copy_shop_id",
        format_func=lambda value: "가게를 선택하세요" if value is None else f"{choices[value]['shop_name']} (#{value})",
        on_change=clear_copy_result)
    if not shops:
        st.info("먼저 가게 프로필을 저장해 주세요")
    if selected is not None and st.session_state.get('copy_loaded_id') != selected:
        try:
            saved = api('GET', f'/profile/{selected}')
            st.session_state.copy_profile = saved['profile']
            st.session_state.copy_loaded_id = selected
            for key in ('copy_menu_selection', 'copy_menu_name', 'copy_menu_price', 'copy_menu_features', 'copy_menu_this_time'):
                st.session_state.pop(key, None)
        except UserApiError as exc:
            st.error(str(exc))
    profile = st.session_state.get('copy_profile', {}) if st.session_state.get('copy_loaded_id') == selected else {}
    menus = profile.get('menus') or []
    labels = [f"{i + 1}. {row['name']}" for i, row in enumerate(menus)]
    if 'copy_menu_selection' not in st.session_state:
        st.session_state.copy_menu_selection = labels[0] if labels else '새 메뉴 직접 입력'
    choice = st.selectbox('소개할 메뉴', [*labels, '새 메뉴 직접 입력'], key='copy_menu_selection', on_change=clear_copy_result)
    revision = (selected, choice)
    if st.session_state.get('copy_menu_revision') != revision:
        row = menus[labels.index(choice)] if choice in labels else {}
        st.session_state.copy_menu_name = row.get('name') or ''
        st.session_state.copy_menu_price = row.get('price') or ''
        st.session_state.copy_menu_revision = revision
        clear_copy_result()
    name = st.text_input('메뉴명 (필수)', key='copy_menu_name', on_change=clear_copy_result)
    price = st.text_input('가격', key='copy_menu_price', on_change=clear_copy_result)
    features = st.text_area('부연 설명 · 이번 메뉴 특징', key='copy_menu_features', on_change=clear_copy_result)
    this_time = st.text_area('부연 설명 · 이번에 알리고 싶은 것', placeholder='예: 이번 주만 1,000원 할인', key='copy_menu_this_time', on_change=clear_copy_result)
    left, right = st.columns(2)
    shop_clicked = left.button('가게 소개 문구', disabled=selected is None, use_container_width=True)
    menu_clicked = right.button('메뉴 문구', type='primary', disabled=selected is None, use_container_width=True)
    if shop_clicked or menu_clicked:
        clear_copy_result()
        mode = 'shop' if shop_clicked else 'menu'
        if mode == 'menu' and not name.strip():
            st.error('메뉴 이름을 적어 주세요')
        else:
            payload = {'mode': mode, 'shop_id': selected}
            if mode == 'menu':
                payload['menu'] = {'name': name.strip(), 'price': blank_to_none(price),
                                   'features': blank_to_none(features), 'this_time': blank_to_none(this_time)}
            try:
                with st.spinner('문구를 만들고 규칙을 확인하고 있어요…'):
                    st.session_state.copy_result = api('POST', '/copy/generate', payload=payload,
                        timeout=GEMINI_TIMEOUT_MS / 1000 * 2 + 20)
            except UserApiError as exc:
                st.error(str(exc))
    result = st.session_state.get('copy_result')
    if result:
        for warning in result.get('warnings', []):
            st.warning(warning)
        info = result.get('regeneration', {})
        if info.get('performed'):
            st.caption(f"규칙 교정 1회 · {info.get('selected_attempt', 1)}번째 결과 선택")
        st.subheader('인스타그램')
        st.text(result['instagram']['body'])
        st.text(' '.join(result['instagram']['hashtags']))
        st.subheader('배달앱')
        delivery = result['delivery_app']
        st.text(delivery.get('shop_intro') or delivery.get('menu_description') or '')
        if result.get('naver_place'):
            st.subheader('네이버 플레이스')
            st.text(result['naver_place']['body'])

        if selected is not None and name.strip():
            render_ad_controls(api, selected, {
                'name': name.strip(), 'price': blank_to_none(price),
                'features': blank_to_none(features), 'this_time': blank_to_none(this_time),
            }, result)
