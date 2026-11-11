import streamlit as st

from app.core import config
from app.services.gemini_retry import request_timeout_seconds
from app.ui.api_client import UserApiError
from app.ui.profile_form import blank_to_none
from app.ui.state import api, empty_result, remember, menu_row, save_shop


def clear_menu_result():
    for key in ("copy_result", "ad_png", "cutout_selection"):
        st.session_state.pop(key, None)


def choose_menu(profile, widget_key):
    state = st.session_state
    menus = profile.get("menus") or []
    labels = [f"{index + 1}. {menu['name']}" for index, menu in enumerate(menus)]
    choices = [*labels, "새 메뉴 직접 입력"]
    selected = state.pop("menu_target", None) or state.get("menu_selection", choices[0])
    if state.pop("sync_menu_picker", False):
        state.pop(widget_key, None)
    selection = st.selectbox("메뉴 고르기", choices, index=choices.index(selected) if selected in choices else 0,
                             key=widget_key)
    if selection != state.get("menu_selection"):
        clear_menu_result()
        values = state.setdefault("page_inputs", {})
        row = menus[labels.index(selection)] if selection in labels else {}
        values.update(copy_menu_name=row.get("name") or "", copy_menu_price=row.get("price") or "")
        for field in ("features", "this_time", "components", "origin"):
            values.pop(f"copy_menu_{field}", None)
        if widget_key == "copy_menu_selection":
            for field in ("name", "price", "features", "this_time", "components", "origin"):
                state.pop(f"copy_menu_{field}", None)
        values["copy_menu_origin"] = state.get("saved_shop", {}).get("menu_origins", {}).get(row.get("name"), "")
        state.menu_selection = selection
        if cached := state.get("quick_results", {}).get("menus", {}).get(row.get("name")):
            for key in ("copy_result", "ad_png", "cutout_selection"):
                if cached.get(key):
                    state[key] = cached[key]
    return selection


def current_menu():
    values = st.session_state.get("page_inputs", {})
    menu = {field: blank_to_none(values.get(f"copy_menu_{field}"))
            for field in ("name", "price", "features", "this_time", "origin")}
    components = values.get("copy_menu_components", "")
    menu["components"] = [part.strip() for part in components.replace("\n", ",").split(",") if part.strip()] or None
    return menu


def render_copy_page(ad_page):
    state = st.session_state
    st.title("문구 만들기")
    st.caption("메뉴와 알리고 싶은 내용을 골라 채널별 문구를 만들어 보세요.")
    left, right = st.columns([5, 7])
    with left.container(border=True, key="card_copy_input"):
        selection = choose_menu(state.saved_profile, "copy_menu_selection")
        remember(st.text_input, "메뉴 이름 (필수)", "copy_menu_name", on_change=clear_menu_result)
        remember(st.text_input, "가격", "copy_menu_price", on_change=clear_menu_result)
        with st.expander("더 알리고 싶은 내용 (선택)"):
            for widget, label, field in (
                (st.text_area, "부연 설명 · 이번 메뉴 특징", "features"),
                (st.text_area, "메뉴 구성", "components"),
                (st.text_input, "메뉴 원산지", "origin"),
                (st.text_area, "이번에 알리고 싶은 것", "this_time"),
            ):
                remember(widget, label, f"copy_menu_{field}", on_change=clear_menu_result)
        menu_clicked = st.button("메뉴 문구 만들기", type="primary", use_container_width=True)
        shop_clicked = st.button("가게 소개 문구", use_container_width=True)
        if menu_clicked or shop_clicked:
            menu = current_menu()
            if menu_clicked and not menu["name"]:
                st.error("메뉴 이름을 적어 주세요")
            else:
                payload = {"mode": "menu" if menu_clicked else "shop", "shop_id": state.shop_id}
                if menu_clicked:
                    payload["menu"] = {field: menu[field] for field in ("name", "price", "features", "this_time")}
                    payload["menu"].update({field: menu[field] for field in ("components", "origin") if menu[field]})
                try:
                    if menu_clicked and selection == "새 메뉴 직접 입력":
                        persist_menu(menu)
                    with st.spinner("문구를 만들고 있어요…"):
                        state.copy_result = api("POST", "/copy/generate", payload=payload,
                                                timeout=request_timeout_seconds(config.GEMINI_TIMEOUT_MS, generations=2))
                    state.pop("ad_png", None)
                    st.rerun()
                except UserApiError as exc:
                    st.error(str(exc))
    with right:
        result = state.get("copy_result")
        if not result:
            empty_result()
            return
        with st.container(border=True, key="card_copy_output"):
            instagram, delivery, naver = st.tabs(["인스타그램", "배달앱", "네이버 플레이스"])
            with instagram:
                st.code(result["instagram"]["body"], language=None, wrap_lines=True)
                st.code(" ".join(result["instagram"]["hashtags"]), language=None, wrap_lines=True)
            with delivery:
                channel = result["delivery_app"]
                st.code(channel.get("shop_intro") or channel.get("menu_description") or "", language=None, wrap_lines=True)
            with naver:
                body = (result.get("naver_place") or {}).get("body")
                if body:
                    st.code(body, language=None, wrap_lines=True)
                else:
                    st.caption("가게 소개 문구를 만들면 여기에서 볼 수 있어요")
            warnings = result.get("warnings", [])
            if warnings:
                with st.expander(f"확인해 볼 점 ({len(warnings)}개)"):
                    for warning in warnings:
                        st.markdown(f"- {warning}")
            st.page_link(ad_page, label="광고 카드 만들러 가기", icon="🖼️")


def persist_menu(menu):
    state = st.session_state
    saved = state.saved_shop
    menus = [dict(item) for item in state.saved_profile.get("menus") or []]
    origins = dict(saved.get("menu_origins") or {})
    index = next((i for i, item in enumerate(menus) if item["name"] == menu["name"]), len(menus))
    if index == len(menus):
        menus.append({"name": menu["name"], "price": menu["price"]})
        if menu["origin"]:
            origins[menu["name"]] = menu["origin"]
    else:
        menus[index]["price"] = menu["price"]
    profile = {**state.saved_profile, "menus": menus}
    payload = {key: saved.get(key) for key in ("shop_id", "source_text", "prompt_version", "concept", "design")}
    old_menus = state.saved_profile.get("menus")
    rows = state.get("menu_rows", [])
    draft = state.get("draft", state.saved_profile)
    draft_menus = [dict(item) for item in draft.get("menus") or []]
    save_shop({**payload, "profile": profile, "menu_origins": origins})
    if draft.get("menus") == old_menus and not state.get("draft_invalid"):
        draft_menus = menus
    else:
        existing = next((item for item in draft_menus if item["name"] == menu["name"]), None)
        if existing:
            existing["price"] = menu["price"]
        else:
            draft_menus.append({"name": menu["name"], "price": menu["price"]})
    draft_row = next((item for item in rows if item["name"].strip() == menu["name"]), None)
    if draft_row:
        # Recreate this row's widget identity so a cached price cannot replace the saved value.
        replacement = menu_row(menu, {menu["name"]: draft_row["origin"]})
        rows = [replacement if item is draft_row else item for item in rows]
    else:
        rows = [*rows, menu_row(menu, origins)]
    state.draft = {**draft, "menus": draft_menus}
    state.menu_rows = rows
    if menu["name"] in origins:
        state.setdefault("draft_origins", {}).setdefault(menu["name"], origins[menu["name"]])
    state.menu_selection = f"{index + 1}. {menu['name']}"
    state.sync_menu_picker = True
