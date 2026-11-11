import base64

import streamlit as st

from app.services.ad_copy import ad_copy
from app.services.design_options import default_design
from app.ui.api_client import UserApiError
from app.ui.copy_tab import choose_menu, current_menu
from app.ui.cutout_preview import render_cutout_preview, show_photo_preview
from app.ui.design_panel import render_design_panel
from app.ui.labels import MENU_LAYOUTS
from app.ui.state import api, empty_result, remember


def show_png(result, name, *, width="stretch"):
    for warning in result.get("warnings", []):
        st.warning(warning)
    png = base64.b64decode(result["png_base64"])
    st.image(png, width=width)
    st.download_button("PNG 받기", png, file_name=name, mime="image/png", key="download_" + name, type="primary")


def render_ad_page():
    state = st.session_state
    st.title("광고 카드")
    st.caption("메뉴 사진을 올리고 디자인을 골라 광고 카드를 만들어 보세요.")
    saved = state.saved_shop
    menu_picker, menu_summary = st.columns(2, vertical_alignment="bottom")
    with menu_picker:
        choose_menu(saved["profile"], "ad_menu_selection")
    menu = current_menu()
    if menu["name"]:
        menu_summary.markdown(" · ".join(part for part in (menu["name"], menu["price"]) if part))
    else:
        st.info("문구 만들기에서 메뉴 이름을 적어 주세요")

    with st.container(border=True, key="card_ad_photo"):
        st.subheader("① 사진 올리기")
        controls, preview = st.columns([5, 7])
        with controls:
            previous = state.get("cutout_selection")
            photo = render_cutout_preview(api, state.shop_id, menu["name"]) if menu["name"] else None
            if photo and previous != state.get("cutout_selection"):
                state.pop("ad_png", None)
        with preview:
            if photo:
                show_photo_preview(photo)
            else:
                st.caption("사진을 올리면 원본과 배경 지운 모습을 볼 수 있어요.")

    with st.container(border=True, key="card_ad_design"):
        st.subheader("② 디자인 고르기")
        if photo:
            render_design_panel(saved, {field: menu[field] for field in ("name", "price")}, photo)
        else:
            st.caption("사진을 올리면 내 사진으로 만든 디자인 후보가 나와요.")

    with st.container(border=True, key="card_ad_output"):
        st.subheader("③ 광고 만들기")
        controls, result = st.columns([5, 7])
        with controls:
            if not state.get("copy_result"):
                st.caption("문구를 먼저 만들면 광고에 문구가 들어가요")
            if not photo:
                st.caption("사진을 올린 뒤 광고 카드를 만들 수 있어요.")
            if st.button("광고 카드 만들기", type="primary", disabled=not (photo or state.get("cutout_selection")), use_container_width=True):
                try:
                    render_ad_result(saved, menu)
                    st.rerun()
                except UserApiError as exc:
                    st.error(str(exc))
        with result:
            if state.get("ad_png"):
                show_png(state.ad_png, "ad_card.png", width=560)
            else:
                empty_result()


def render_ad_result(saved, menu):
    with st.spinner("광고 카드를 만들고 있어요…"):
        st.session_state.ad_png = build_ad(saved["shop_id"], menu, st.session_state.get("cutout_selection"),
                                           saved.get("design"), st.session_state.get("copy_result"))


def build_ad(shop_id, menu, selection, design, generated):
    copy = ad_copy(generated or {})
    design = design or {}
    payload = {'shop_id': shop_id, 'menu': menu, **copy, 'origin': menu.get('origin')}
    if selection:
        mode = selection['mode']
        use_studio = (design.get('ad_layout') in ('cutout_studio', 'receipt', 'big_price') and mode == 'cutout'
                      and not selection.get('suggest_original'))
        if use_studio:
            payload['cutout_url'] = 'data:image/png;base64,' + selection['png_base64']
            payload['photo_url'] = 'data:image/png;base64,' + selection['original_png_base64']
        elif design.get('ad_layout') in ('cutout_studio', 'receipt', 'big_price') and selection.get('suggest_original'):
            mode = 'original'
        payload['suggest_original'] = mode == 'original' or bool(selection.get('suggest_original'))
        if mode == 'cutout':
            payload['cutout_url'] = 'data:image/png;base64,' + selection['png_base64']
        photo_field = 'photo_base64' if mode == 'original' else 'cutout_png_base64'
        if not use_studio:
            photo = selection['original_png_base64'] if mode == 'original' else selection['png_base64']
            result = api('POST', '/image/compose', payload={
                'shop_id': shop_id, 'mode': mode, photo_field: photo,
            }, timeout=320)
            payload['photo_url'] = 'data:image/png;base64,' + result['composite_png_base64']
    if design:
        payload['design'] = design
    return api('POST', '/render/ad-card', payload=payload, timeout=120)

def render_menu_page():
    state = st.session_state
    st.title("메뉴판")
    st.caption("가게 메뉴를 한 장에 정리하고 PNG로 받아 보세요.")
    left, right = st.columns([5, 7])
    with left.container(border=True, key="card_board_input"):
        saved = state.saved_shop
        menus = saved["profile"].get("menus") or []
        photos = state.get("menu_photos", {}).get(state.shop_id, {})
        count = sum(menu["name"] in photos for menu in menus)
        st.caption(f"사진 {count}/{len(menus)}개, 사진 없는 메뉴는 글자로만 나와요")
        design = saved.get("design") or default_design(saved["profile"].get("business_type")).model_dump()
        layout = remember(st.selectbox, "메뉴판 레이아웃", f"board_layout_{state.shop_id}", design["menu_layout"],
                          options=list(MENU_LAYOUTS), format_func=MENU_LAYOUTS.__getitem__,
                          on_change=lambda: state.pop("board_png", None))
        if st.button("메뉴판 만들기", type="primary", use_container_width=True):
            try:
                with st.spinner("메뉴판을 만들고 있어요…"):
                    payload = {"shop_id": state.shop_id, "design": {**design, "menu_layout": layout}}
                    if photos and menus:
                        payload["menus"] = [{**menu, "photo_url": photos.get(menu["name"], {}).get("url")} for menu in menus]
                    state.board_png = api("POST", "/render/menu-board", payload=payload, timeout=120)
                st.rerun()
            except UserApiError as exc:
                st.error(str(exc))
    with right:
        if state.get("board_png"):
            with st.container(border=True, key="card_board_output"):
                show_png(state.board_png, "menu_board.png")
        else:
            empty_result()
