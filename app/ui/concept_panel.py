import streamlit as st
from app.core.config import GEMINI_TIMEOUT_MS
from app.schemas.concept import allowed_themes
from app.ui.api_client import UserApiError
from app.ui.concept_form import concept_from_form
from app.ui.profile_form import form_to_profile


def render_concept_panel(api, values, menu_rows, draft, revision):
    stored = st.session_state.get('draft_concept')
    if (values.get('mood_strengths') or '').strip() or (values.get('tone') or '').strip():
        if stored:
            st.caption('프로필에 적은 분위기·말투를 우선 사용해요')
        return stored
    st.subheader('표현 컨셉 (선택)')
    st.caption('가게의 사실이 아닌 표현 방향이에요. 고르지 않아도 저장할 수 있어요')
    prefix = f'concept_{revision}'
    if st.button('컨셉 추천받기'):
        try:
            profile = form_to_profile(values, menu_rows, draft.get('needs_check'))
            with st.spinner('컨셉 후보를 생각하고 있어요…'):
                response = api('POST', '/profile/suggest-concept', payload={'profile': profile}, timeout=GEMINI_TIMEOUT_MS / 1000 + 20)
            st.session_state[prefix + '_candidates'] = response['candidates']
            st.session_state[prefix + '_round'] = st.session_state.get(prefix + '_round', 0) + 1
        except (UserApiError, ValueError) as exc:
            st.warning(str(exc))
    candidates = st.session_state.get(prefix + '_candidates', [])
    round_number = st.session_state.get(prefix + '_round', 0)
    options = ['none', *range(len(candidates)), 'direct']
    if stored:
        options.insert(1, 'saved')
    labels = {'none': '고르지 않기', 'direct': '직접 쓰기', 'saved': '저장된 컨셉'}
    selected = st.radio('컨셉 선택', options, index=1 if stored else 0,
        format_func=lambda value: labels[value] if isinstance(value, str) else candidates[value]['name'],
        key=f'{prefix}_{round_number}_choice')
    if selected == 'none':
        return None
    original = stored if selected == 'saved' else candidates[selected] if isinstance(selected, int) else None
    original = original or {}
    edit_key = f'{prefix}_{round_number}_{selected}'
    fields = {}
    for field, label in (('name', '컨셉 이름 (10자 안쪽)'), ('mood', '컨셉 분위기'), ('tone', '컨셉 말투')):
        fields[field] = st.text_input(label, value=original.get(field, ''), key=f'{edit_key}_{field}')
    themes = allowed_themes()
    fields['theme'] = st.selectbox('컨셉 테마', themes, index=themes.index(original.get('theme', '기본')), key=f'{edit_key}_theme')
    # Validation runs only on save so incomplete optional edits do not break reruns.
    return {'values': fields, 'original': original}


def selected_concept(panel):
    if panel is None:
        return None
    if 'values' in panel:
        return concept_from_form(panel['values'], panel['original'])
    return panel
