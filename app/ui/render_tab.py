import base64
import streamlit as st
from app.ui.api_client import UserApiError


def show_png(result, name):
    for warning in result['warnings']:
        st.warning(warning)
    png = base64.b64decode(result['png_base64'])
    st.image(png)
    st.download_button('PNG 다운로드', png, file_name=name, mime='image/png', key='download_' + name)


def render_ad_controls(api, shop_id, menu, generated):
    st.subheader('광고 카드')
    headline = st.text_input('광고 첫 문장', value=generated['instagram']['body'].splitlines()[0], key='ad_headline')
    body = st.text_area('광고 본문', value=generated['delivery_app']['body'], key='ad_body')
    if st.button('광고 카드 만들기'):
        try:
            with st.spinner('광고 카드를 만들고 있어요…'):
                st.session_state.ad_png = api('POST', '/render/ad-card', payload={'shop_id': shop_id, 'menu': menu, 'headline': headline, 'body': body}, timeout=120)
        except UserApiError as exc:
            st.error(str(exc))
    if st.session_state.get('ad_png'):
        show_png(st.session_state.ad_png, 'ad_card.png')
