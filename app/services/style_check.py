"""Pure checks for press-release wording in delivery and Place copy."""
import re

PRESS_RELEASE_EXPRESSIONS = ('매력', '풍미', '선보이다', '갖추다', '돋보이다', '살려요', '입맛을 당겨요')
_PATTERNS = {
    '선보이다': r'선보',
    '갖추다': r'갖(?:추|춰|춘|췄)',
    '돋보이다': r'돋보',
    '살려요': r'살(?:려|리|린|렸)',
    '입맛을 당겨요': r'입맛\s*을\s*당(?:겨|기|긴|겼)',
}


def style_warnings(generated) -> list[str]:
    warnings = []
    for channel, label in (('delivery_app', '배달앱'), ('naver_place', '네이버 플레이스')):
        text = getattr(generated, channel).body
        for expression in PRESS_RELEASE_EXPRESSIONS:
            if re.search(_PATTERNS.get(expression, re.escape(expression)), text):
                warnings.append(f"{label}에 금지 표현 '{expression}'이 들어갔어요")
    return warnings
