import base64
import logging
from time import perf_counter

import streamlit as st

from app.core import config
from app.services.gemini_retry import request_timeout_seconds
from app.ui.api_client import UserApiError
from app.ui.render_tab import build_ad, show_png
from app.ui.state import api, clear_results, save_shop, set_draft


def generate_quick(saved, uploads, report):
    started = perf_counter()
    shop_id = saved["shop_id"]
    timeout = request_timeout_seconds(config.GEMINI_TIMEOUT_MS, generations=2)
    results = {"menus": {}, "errors": [], "shop_id": shop_id}

    def step(label, action):
        report(label)
        try:
            return action()
        except UserApiError as exc:
            results["errors"].append(f"{label} · {exc}")
            return None

    results["shop_copy"] = step("가게 소개 문구", lambda: api(
        "POST", "/copy/generate", payload={"shop_id": shop_id, "mode": "shop"}, timeout=timeout))
    photos = {}
    results["defer_ads"] = len(uploads) >= 3
    for index, (menu, upload) in enumerate(uploads[:3]):
        name = menu["name"]
        item = results["menus"][name] = {}
        photo = step(f"{name} 배경 분리", lambda: api("POST", "/image/cutout", payload={
            "photo_base64": base64.b64encode(upload).decode("ascii")}, timeout=120))
        if not photo:
            continue
        item["photo"] = photo
        original = photo["original_png_base64"]
        photos[name] = {"url": "data:image/png;base64," + original,
                        "suggest_original": photo["suggest_original"]}
        mode = "original" if photo["suggest_original"] else "cutout"
        item["cutout_selection"] = selection = {
            "mode": mode, "png_base64": photo[f"{mode}_png_base64"],
            "original_png_base64": original, "suggest_original": photo["suggest_original"],
        }
        item["copy_result"] = copy = step(f"{name} 메뉴 문구", lambda: api(
            "POST", "/copy/generate", payload={"shop_id": shop_id, "mode": "menu", "menu": menu}, timeout=timeout))
        if not copy:
            continue
        candidates = step(f"{name} 디자인 후보", lambda: api("POST", "/profile/suggest-concept", payload={
            "shop_id": shop_id, "menu_name": name, "suggest_original": photo["suggest_original"],
            "photo_menu_count": len(uploads[:3]),
        }, timeout=timeout))
        if not candidates or not candidates.get("candidates"):
            continue
        item["candidates"] = candidates
        design = {**candidates["candidates"][0]["design"], "source": candidates.get("source", "추천"),
                  "lang": "ko", "show_origin": False}
        if not results.get("design_saved"):
            fields = ("shop_id", "profile", "source_text", "prompt_version", "concept", "menu_origins")
            if not step("첫 디자인 저장", lambda: save_shop({
                **{field: saved.get(field) for field in fields}, "design": design,
            })):
                continue
            results["design_saved"] = True
        if index == 0 or not results.get("defer_ads"):
            item["ad_png"] = step(f"{name} 광고 카드", lambda: build_ad(shop_id, menu, selection, design, copy))
        else:
            item["pending_ad"] = (menu, design)

    if menus := saved["profile"].get("menus"):
        results["board"] = step("메뉴판", lambda: api("POST", "/render/menu-board", payload={
            "shop_id": shop_id, "menus": [
                {**menu, "photo_url": photos.get(menu["name"], {}).get("url")} for menu in menus
            ],
        }, timeout=timeout))
    results["photos"] = photos
    results["seconds"] = perf_counter() - started
    logging.getLogger(__name__).warning("Quick generation shop=%s photos=%s elapsed=%.2fs",
                                       shop_id, len(uploads[:3]), results["seconds"])
    return results


def render_quick_page(profile_page, copy_page, ad_page):
    state = st.session_state
    st.title("✨ 한 번에 만들기")
    source = st.text_area("가게 소개 글", height=220,
                          placeholder="가게 이름, 업종, 메뉴와 가격, 분위기를 편하게 적어 주세요.")
    if st.button("정리하고 시작", type="primary", disabled=not source.strip()):
        try:
            with st.spinner("가게 소개를 정리하고 있어요…"):
                extracted = api("POST", "/profile/extract", payload={"text": source, "prompt_version": "v2"},
                                timeout=request_timeout_seconds(config.GEMINI_TIMEOUT_MS))
            state.quick_pending = {"profile": extracted, "source_text": source}
            state.pop("quick_results", None)
        except UserApiError as exc:
            st.error(str(exc))
    if pending := state.get("quick_pending"):
        extracted = dict(pending["profile"])
        missing = [key for key in ("shop_name", "business_type") if not extracted.get(key)]
        for key in missing:
            extracted[key] = st.text_input("가게 이름" if key == "shop_name" else "업종",
                                           key=f"quick_required_{key}").strip()
        if not missing or st.button("입력한 정보로 시작", disabled=not all(extracted.get(key) for key in missing)):
            try:
                saved = save_shop({**pending, "profile": extracted, "shop_id": None, "prompt_version": "v2"})
                set_draft(extracted, pending["source_text"], saved["shop_id"],
                          concept=state.saved_shop.get("concept"))
                state.pop("quick_pending")
                state.pop("menu_selection", None)
                clear_results()
                st.rerun()
            except UserApiError as exc:
                st.error(str(exc))
        return
    if not state.get("saved_shop"):
        return
    saved = state.saved_shop
    if checks := saved["profile"].get("needs_check"):
        st.warning("\n".join(checks))
    uploads = []
    for index, menu in enumerate(saved["profile"].get("menus") or []):
        with st.container(border=True):
            st.write(" · ".join(filter(None, (menu["name"], menu.get("price")))))
            photo = st.file_uploader("메뉴 사진 (선택)", type=["jpg", "jpeg", "png"],
                                     key=f"quick_photo_{saved['shop_id']}_{index}")
            if photo:
                uploads.append(({**menu, "origin": (saved.get("menu_origins") or {}).get(menu["name"])}, photo.getvalue()))
    if len(uploads) > 3:
        st.info("사진이 있는 메뉴 중 앞의 3개를 만들어요.")
    if st.button("광고 한 번에 만들기", type="primary"):
        with st.status("광고를 만들고 있어요…", expanded=True) as status:
            state.quick_results = generate_quick(saved, uploads, st.write)
            state.setdefault("menu_photos", {}).setdefault(saved["shop_id"], {}).update(state.quick_results["photos"])
            status.update(label="만들기 완료", state="complete")
    result = state.get("quick_results")
    if not result or result["shop_id"] != saved["shop_id"]:
        return
    st.caption(f"걸린 시간 {result['seconds']:.1f}초")
    if result.get("defer_ads"):
        st.info("첫 광고를 먼저 만들었어요. 나머지 광고는 아래 버튼에서 한 장씩 만들 수 있어요.")
    for name, item in result["menus"].items():
        if item.get("pending_ad") and st.button(f"{name} 광고 카드 만들기", key=f"quick_pending_ad_{name}"):
            menu, design = item["pending_ad"]
            try:
                with st.spinner("광고 카드를 만들고 있어요…"):
                    item["ad_png"] = build_ad(saved["shop_id"], menu, item["cutout_selection"], design, item["copy_result"])
                item.pop("pending_ad")
                st.rerun()
            except UserApiError as exc:
                st.error(str(exc))
    for error in result["errors"]:
        st.warning(error)
    ads = [(name, item) for name, item in result["menus"].items() if item.get("ad_png")]
    if ads:
        for index, (column, (name, item)) in enumerate(zip(st.columns(len(ads)), ads)):
            with column:
                st.subheader(name)
                show_png(item["ad_png"], f"quick_ad_{index}.png")
                links = (("디자인 바꾸기", ad_page), ("문구 다시 만들기", copy_page))
                for label, page in links if any(menu["name"] == name for menu in saved["profile"].get("menus") or []) else ():
                    if st.button(label, key=f"quick_{index}_{label}"):
                        select_result(name)
                        st.switch_page(page)
                st.page_link(profile_page, label="가게 정보 고치기")
    if result.get("board"):
        st.subheader("메뉴판")
        show_png(result["board"], "quick_menu_board.png", width=560)
        st.page_link(profile_page, label="가게 정보 고치기")
    copies = [("가게 소개", result.get("shop_copy"))] + [
        (name, item.get("copy_result")) for name, item in result["menus"].items()
    ]
    copies = [(name, copy) for name, copy in copies if copy]
    if copies:
        for tab, (_, copy) in zip(st.tabs([name for name, _ in copies]), copies):
            with tab:
                st.write(copy["instagram"]["body"])
                st.write(" ".join(copy["instagram"]["hashtags"]))
                st.write(next(iter(copy["delivery_app"].values()), ""))
                if copy.get("naver_place"):
                    st.write(copy["naver_place"]["body"])


def select_result(name):
    state = st.session_state
    menus = state.saved_profile.get("menus") or []
    index = next(i for i, menu in enumerate(menus) if menu["name"] == name)
    state.pop("menu_selection", None)
    state.menu_target = f"{index + 1}. {name}"
    state.sync_menu_picker = True
