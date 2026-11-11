from uuid import uuid4

import streamlit as st

from app.core import config
from app.core.config import API_BASE_URL
from app.services.gemini_retry import request_timeout_seconds
from app.ui import api_client


def api(method, path, **kwargs):
    return api_client.request_api(API_BASE_URL, method, path, **kwargs)


def remember(widget, label, key, default="", *, options=None, on_change=None, **kwargs):
    values = st.session_state.setdefault("page_inputs", {})
    value = values.get(key, default)
    if options is None:
        result = widget(label, value=value, key=key, on_change=on_change, **kwargs)
    else:
        index = options.index(value) if value in options else 0
        result = widget(label, options, index=index, key=key, on_change=on_change, **kwargs)
    values[key] = result
    return result


def clear_results():
    for key in ("copy_result", "ad_png", "board_png", "cutout_selection"):
        st.session_state.pop(key, None)


def set_draft(profile, source_text, shop_id=None, version="v2", concept=None, design=None, menu_origins=None):
    state = st.session_state
    state.draft_invalid = False
    state.draft = profile
    state.draft_source = source_text
    state.draft_design = design
    state.draft_concept = concept
    state.draft_origins = menu_origins or {}
    state.shop_id = shop_id
    state.prompt_version = version
    state.draft_revision = state.get("draft_revision", 0) + 1
    state.pop("saved_notice", None)
    state.menu_rows = [menu_row(menu, state.draft_origins) for menu in profile.get("menus") or []]


def empty_result():
    with st.container(border=True, key="card_empty_result"):
        st.caption("여기에 결과가 나와요")


def menu_row(menu=None, origins=None):
    menu = menu or {}
    name = menu.get("name") or ""
    return dict(id=uuid4().hex, name=name, price=menu.get("price") or "",
                origin=(origins or {}).get(name) or "")


def save_shop(payload):
    state = st.session_state
    result = api("POST", "/profile/save", payload=payload,
                 timeout=request_timeout_seconds(config.GEMINI_TIMEOUT_MS))
    concept = result.get("concept", payload.get("concept"))
    state.saved_shop = {**payload, "shop_id": result["shop_id"], "concept": concept}
    state.draft_concept = concept
    state.saved_profile = payload["profile"]
    state.shop_id = result["shop_id"]
    state.reload_shops = state.sync_saved_selection = True
    return result
