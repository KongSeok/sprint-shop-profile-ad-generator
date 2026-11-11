import base64
from hashlib import sha256
from html import escape

import streamlit as st

from app.services.design_options import default_design
from app.services.template_v3 import styles
from app.ui.api_client import UserApiError
from app.ui.concept_panel import request_candidates
from app.ui.labels import AD_LAYOUTS, MENU_LAYOUTS, STYLES
from app.ui.state import api, remember, save_shop


def save_design(saved, design):
    fields = ("shop_id", "profile", "source_text", "prompt_version", "concept", "menu_origins")
    save_shop({**{field: saved.get(field) for field in fields}, "design": design})
    st.session_state.draft_design = design
    for key in ("ad_png", "board_png"):
        st.session_state.pop(key, None)
    st.session_state.get("page_inputs", {}).pop(f"board_layout_{saved['shop_id']}", None)
    st.session_state.design_notice = design
    st.rerun()


def render_design_panel(saved, menu, photo_preview):
    state = st.session_state
    shop_id = saved["shop_id"]
    photo = state.menu_photos[shop_id][menu["name"]]
    fingerprint = sha256(photo["url"].encode()).hexdigest()
    prefix = f"ad_design_{shop_id}_{fingerprint}_{menu['name']}"
    profile = saved["profile"]
    stored = saved.get("design") or default_design(profile.get("business_type")).model_dump()
    if not state.get(f"{prefix}_attempted"):
        quick = state.get("quick_results", {})
        cached = quick.get("menus", {}).get(menu["name"], {}).get("candidates")
        if quick.get("shop_id") == shop_id and cached:
            state[f"{prefix}_candidates"] = cached["candidates"]
            state[f"{prefix}_source"] = cached.get("source", "추천")
            state[f"{prefix}_attempted"] = True
    requested = st.button("다른 후보 보기", key=f"{prefix}_request")
    if requested or not state.get(f"{prefix}_attempted"):
        state[f"{prefix}_attempted"] = True
        request_candidates(api, profile, prefix, menu["name"], shop_id=shop_id)

    number = state.get(f"{prefix}_round", 0)
    candidates = state.get(f"{prefix}_candidates", [])
    uses_original = state.get("cutout_selection", {}).get("mode") == "original"
    if candidates:
        for index, (column, candidate) in enumerate(zip(st.columns(3), candidates), 1):
            design = {**candidate["design"], "source": state.get(f"{prefix}_source", "추천"),
                      "lang": stored.get("lang", "ko"), "show_origin": stored.get("show_origin", False)}
            active = all(stored.get(key) == value for key, value in design.items())
            with column.container(border=True, key=f"candidate_{index}_{'selected' if active else 'idle'}"):
                preview_key = f"{prefix}_{number}_{index}_thumbnail"
                if preview_key not in state:
                    try:
                        payload = {"profile": profile, "menu": menu, "photo_url": photo["url"], "design": design}
                        if not photo.get("suggest_original"):
                            payload["cutout_url"] = "data:image/png;base64," + photo_preview[1]
                        result = api("POST", "/render/ad-card", payload=payload, timeout=120)
                        state[preview_key] = base64.b64decode(result["png_base64"])
                    except UserApiError as exc:
                        st.warning(str(exc))
                if preview_key in state:
                    st.image(state[preview_key], width="stretch")
                if uses_original and design["ad_layout"] in ("cutout_studio", "receipt", "big_price"):
                    st.caption("사진 그대로면 '사진 꽉 차게'로 바뀌어요")
                title = f"{STYLES[design['style']]} · {AD_LAYOUTS[design['ad_layout']]}"
                st.markdown(f'<div class="design-title" aria-label="후보 {index} · {title}">{title}</div>',
                            unsafe_allow_html=True)
                st.markdown(f"<div class='design-reason'>{escape(design['reason'])}</div>", unsafe_allow_html=True)
                if active:
                    st.markdown('<div class="design-selected">✓ 고른 디자인</div>', unsafe_allow_html=True)
                if st.button("이걸로", key=f"{prefix}_{number}_{index}_pick", disabled=active):
                    try:
                        save_design(saved, design)
                    except UserApiError as exc:
                        st.error(str(exc))
    with st.expander("직접 고르기"):
        render_direct_design(saved, stored, prefix)
    if state.get("design_notice") == saved.get("design"):
        st.success("이 디자인으로 저장했어요")


def render_direct_design(saved, stored, prefix):
    catalog = styles()
    design = dict(stored)
    style = remember(st.selectbox, "스타일", f"{prefix}_style", stored["style"],
                     options=list(catalog), format_func=STYLES.__getitem__)
    design["style"] = style
    for field, label, labels in (
        ("palette", "색 조합", {key: f"색 {i}" for i, key in enumerate(catalog[style]["palettes"], 1)}),
        ("font", "글꼴", {key: f"글꼴 {i}" for i, key in enumerate(catalog[style]["fonts"], 1)}),
        ("ad_layout", "광고 레이아웃", AD_LAYOUTS),
        ("menu_layout", "메뉴판 레이아웃", MENU_LAYOUTS),
        ("lang", "영어 표시", {"ko": "한글만", "ko_en": "작게 영어", "en_ko": "영어 크게"}),
    ):
        control = st
        if field == "palette":
            control, swatches = st.columns([3, 1], vertical_alignment="bottom")
        design[field] = remember(control.selectbox, label, f"{prefix}_{style}_{field}", stored.get(field),
                                 options=list(labels), format_func=labels.__getitem__)
        if field == "palette":
            palette = catalog[style]["palettes"][design[field]]
            swatches.markdown("".join(f'<span class="palette-dot" style="background:{palette[color]}"></span>'
                                     for color in ("bg", "ink", "accent")), unsafe_allow_html=True)
    design["show_origin"] = remember(st.checkbox, "원산지 표시", f"{prefix}_origin", stored.get("show_origin", False))
    if st.button("이 디자인으로 저장", key=f"{prefix}_save"):
        try:
            save_design(saved, {**design, "source": "직접", "reason": "사장님이 직접 선택한 디자인입니다."})
        except UserApiError as exc:
            st.error(str(exc))
