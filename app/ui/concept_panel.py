import streamlit as st
from app.core.config import GEMINI_TIMEOUT_MS
from app.services.gemini_retry import request_timeout_seconds
from app.ui.api_client import UserApiError
from app.ui.concept_form import concept_from_form
from app.ui.profile_form import form_to_profile
from app.ui.state import remember


def request_candidates(api, profile, prefix, menu_name=None, *, shop_id=None):
    try:
        with st.spinner('디자인과 표현 후보를 생각하고 있어요…'):
            if menu_name is None:
                menu_name = next((menu['name'] for menu in profile.get('menus') or []), None)
            if shop_id is None:
                shop_id = st.session_state.get('shop_id')
            shop_photos = st.session_state.get('menu_photos', {}).get(shop_id, {})
            original = bool(shop_photos.get(menu_name, {}).get('suggest_original'))
            photo_menu_count = len({row['name'] for row in profile.get('menus') or []} & shop_photos.keys())
            source = {'shop_id': shop_id} if shop_id and profile == st.session_state.get('saved_profile') else {'profile': profile}
            response = api('POST', '/profile/suggest-concept', payload={
                **source, 'menu_name': menu_name, 'suggest_original': original,
                **({'shop_seed': shop_id} if shop_id else {}),
                'photo_menu_count': min(photo_menu_count, 12),
            },
                           timeout=request_timeout_seconds(GEMINI_TIMEOUT_MS))
        if response.get('fallback_reason'):
            st.warning(response['fallback_reason'])
        st.session_state[prefix + '_candidates'] = response['candidates']
        st.session_state[prefix + '_menu'] = menu_name
        st.session_state[prefix + '_source'] = response.get('source', '추천')
        st.session_state[prefix + '_round'] = st.session_state.get(prefix + '_round', 0) + 1
        return True
    except (UserApiError, ValueError) as exc:
        st.warning(str(exc))
        return False


def render_concept_panel(api, values, menu_rows, draft, revision):
    stored = st.session_state.get('draft_concept')
    if (values.get('mood_strengths') or '').strip() or (values.get('tone') or '').strip():
        if stored:
            st.caption('프로필에 적은 분위기·말투를 우선 사용해요')
        return stored
    st.caption('고르지 않으면 가게 소개 글을 읽고 자동으로 정해요')
    prefix = f'concept_{revision}'
    if not st.session_state.get(prefix + '_candidates') and not st.session_state.get('draft_design'):
        if st.button('컨셉 추천받기'):
            try:
                profile = form_to_profile(values, menu_rows, draft.get('needs_check'))
                request_candidates(api, profile, prefix)
            except ValueError as exc:
                st.warning(str(exc))
    candidates = st.session_state.get(prefix + '_candidates', [])
    round_number = st.session_state.get(prefix + '_round', 0)
    options = ['none', *range(len(candidates)), 'direct']
    if stored:
        options.insert(1, 'saved')
    labels = {'none': '자동으로 정하기', 'direct': '직접 쓰기', 'saved': '저장된 컨셉 (자동)' if stored and stored.get('source') == '자동' else '저장된 컨셉'}
    selected = remember(st.radio, '컨셉 선택', f'{prefix}_{round_number}_choice', 'saved' if stored else 'none', options=options,
        format_func=lambda value: labels[value] if isinstance(value, str) else candidates[value]['name'])
    if selected == 'none':
        return None
    original = stored if selected == 'saved' else candidates[selected] if isinstance(selected, int) else None
    original = original or {}
    edit_key = f'{prefix}_{round_number}_{selected}'
    fields = {}
    for field, label in (('name', '컨셉 이름 (10자 안쪽)'), ('mood', '컨셉 분위기'), ('tone', '컨셉 말투')):
        fields[field] = remember(st.text_input, label, f'{edit_key}_{field}', original.get(field, ''))
    fields['theme'] = original.get('theme', '기본')
    # Validation runs only on save so incomplete optional edits do not break reruns.
    return {'values': fields, 'original': original}


def selected_concept(panel):
    if panel is None:
        return None
    if 'values' in panel:
        return concept_from_form(panel['values'], panel['original'])
    return panel
