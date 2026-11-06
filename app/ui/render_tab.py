import base64
import streamlit as st
from app.ui.api_client import UserApiError


def show_png(result, name):
    for warning in result['warnings']:
        st.warning(warning)
    png = base64.b64decode(result['png_base64'])
    st.image(png)
    st.download_button('PNG 다운로드', png, file_name=name, mime='image/png', key='download_' + name)


def clear_ad_png():
    st.session_state.pop('ad_png', None)


def clear_board_png():
    st.session_state.pop('board_png', None)


def render_ad_controls(api, shop_id, menu, generated):
    st.subheader('광고 카드')
    instagram = generated['instagram']['body']
    delivery = generated.get('delivery_app', {})
    place = generated.get('naver_place') or {}
    default_body = (delivery.get('menu_description') or delivery.get('shop_intro')
                    or delivery.get('body') or place.get('body') or instagram)
    headline = st.text_input('광고 첫 문장', value=next((line.strip() for line in instagram.splitlines() if line.strip()), ''), key='ad_headline', on_change=clear_ad_png)
    body = st.text_area('광고 본문', value=default_body, key='ad_body', on_change=clear_ad_png)
    if st.button('광고 카드 만들기'):
        try:
            with st.spinner('광고 카드를 만들고 있어요…'):
                st.session_state.ad_png = api('POST', '/render/ad-card', payload={'shop_id': shop_id, 'menu': menu, 'headline': headline, 'body': body}, timeout=120)
        except UserApiError as exc:
            st.error(str(exc))
    if st.session_state.get('ad_png'):
        show_png(st.session_state.ad_png, 'ad_card.png')


def render_menu_tab(api, shops):
    st.header('메뉴판 만들기')
    choices = {shop['id']: shop for shop in shops}
    selected = st.selectbox('메뉴판을 만들 가게', [None, *choices], key='board_shop_id', on_change=clear_board_png, format_func=lambda value: '가게를 선택하세요' if value is None else choices[value]['shop_name'])
    if st.button('메뉴판 만들기', disabled=selected is None):
        try:
            with st.spinner('메뉴판을 만들고 있어요…'):
                st.session_state.board_png = api('POST', '/render/menu-board', payload={'shop_id': selected}, timeout=120)
        except UserApiError as exc:
            st.error(str(exc))
    if st.session_state.get('board_png'):
        show_png(st.session_state.board_png, 'menu_board.png')
