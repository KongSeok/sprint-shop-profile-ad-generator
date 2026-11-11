import streamlit as st

from app.core import config
from app.services.gemini_retry import request_timeout_seconds
from app.ui.api_client import UserApiError
from app.ui.concept_panel import render_concept_panel, selected_concept
from app.ui.profile_form import LIST_FIELDS, TEXT_FIELDS, form_to_profile, list_to_lines
from app.ui.state import api, empty_result, remember, set_draft, menu_row, save_shop


def clear_saved_notice():
    st.session_state.pop("saved_notice", None)


def add_menu():
    st.session_state.menu_rows.append(menu_row())
    clear_saved_notice()


def delete_menu(row_id):
    state = st.session_state
    state.menu_rows = [item for item in state.menu_rows if item["id"] != row_id]
    clear_saved_notice()


def render_profile_page(copy_page):
    state = st.session_state
    st.title("가게 정보")
    st.caption("가게 소개를 적고, 메뉴와 가격을 확인해 주세요.")
    left, right = st.columns([5, 7])
    with left.container(border=True, key="card_profile_source"):
        source_revision = state.get("source_revision", 0)
        source_key = f"source_input_{source_revision}" if source_revision else "source_input"
        source = remember(st.text_area, "가게 소개 글", source_key,
                          state.get("draft_source", ""), height=260, on_change=clear_saved_notice)
        if st.button("정리하기", type="primary", use_container_width=True):
            if not source.strip():
                st.info("가게 소개를 먼저 적어 주세요")
            else:
                try:
                    with st.spinner("가게 소개를 정리하고 있어요…"):
                        extracted = api("POST", "/profile/extract", payload={"text": source, "prompt_version": "v2"},
                                        timeout=request_timeout_seconds(config.GEMINI_TIMEOUT_MS))
                    set_draft(extracted, source, state.get("shop_id"), design=state.get("draft_design"),
                              menu_origins=state.get("draft_origins"))
                except UserApiError as exc:
                    st.error(str(exc))
                    if exc.code == "LLM_QUOTA_EXHAUSTED" and "draft" not in state:
                        set_draft({}, source, state.get("shop_id"))
    with right:
        if "draft" in state:
            with st.container(border=True, key="card_profile_details"):
                render_profile_form(copy_page)
        else:
            empty_result()


def render_profile_form(copy_page):
    state = st.session_state
    draft = state.draft
    revision = state.draft_revision
    st.subheader("이렇게 이해했어요")
    if draft.get("needs_check"):
        details = "\n".join(f"- {item}" for item in draft["needs_check"])
        st.warning(f"글에서 서로 다른 내용이 있어요. 확인해 주세요.\n\n{details}")
    values = {}
    for field in ("shop_name", "business_type"):
        values[field] = remember(st.text_input, TEXT_FIELDS[field], f"draft_{revision}_{field}",
                                 draft.get(field) or "", on_change=clear_saved_notice)
    st.write("대표 메뉴·가격")
    menu_rows = state.menu_rows
    for row in menu_rows:
        columns = st.columns([4, 3, 3, 1], vertical_alignment="bottom")
        for column, (field, label) in zip(columns, (("name", "메뉴 이름"), ("price", "가격"), ("origin", "원산지"))):
            key = f"menu_{row['id']}_{field}"
            row[field] = column.text_input(label, value=row[field], key=key, on_change=clear_saved_notice)
        columns[3].button("🗑", key=f"delete_{row['id']}", help="메뉴 삭제",
                          on_click=delete_menu, args=(row["id"],))
    st.button("＋ 메뉴 추가", on_click=add_menu)
    with st.expander("더 적고 싶은 정보 (선택)"):
        for field, label in TEXT_FIELDS.items():
            if field not in values:
                values[field] = remember(st.text_input, label, f"draft_{revision}_{field}",
                                         draft.get(field) or "", on_change=clear_saved_notice)
        for field, label in LIST_FIELDS.items():
            values[field] = remember(st.text_area, f"{label} (한 줄에 하나씩)", f"draft_{revision}_{field}",
                                     list_to_lines(draft.get(field)), on_change=clear_saved_notice)
        st.markdown("**가게 분위기·말투 추천 (선택)**")
        concept_panel = render_concept_panel(api, values, menu_rows, draft, revision)
    try:
        state.draft = form_to_profile(values, menu_rows, draft.get("needs_check"))
    except ValueError:
        state.draft_invalid = True
    else:
        state.draft_invalid = False
    state.draft_origins = menu_origins(menu_rows)
    if st.button("저장", type="primary", use_container_width=True):
        try:
            profile = form_to_profile(values, menu_rows, draft.get("needs_check"))
            if not profile["shop_name"] or not profile["business_type"]:
                raise ValueError("가게 이름과 업종은 꼭 적어 주세요")
            concept = selected_concept(concept_panel)
            origins = menu_origins(menu_rows)
            result = save_shop({
                "shop_id": state.get("shop_id"), "profile": profile, "source_text": state.draft_source,
                "prompt_version": state.prompt_version, "concept": concept, "design": state.get("saved_shop", {}).get("design") or state.get("draft_design"),
                "menu_origins": origins,
            })
            state.saved_profile = state.draft = profile
            state.draft_origins = origins
            state.shop_id = result["shop_id"]
            state.saved_notice = result["shop_id"]
            state.reload_shops = state.sync_saved_selection = True
            st.rerun()
        except (UserApiError, ValueError) as exc:
            st.error(str(exc))
    if state.get("saved_notice"):
        st.success("저장했어요")
        st.page_link(copy_page, label="문구 만들러 가기", icon="✍️")


def menu_origins(rows):
    return {row["name"].strip(): row["origin"].strip() for row in rows
            if row["name"].strip() and row["origin"].strip()}
