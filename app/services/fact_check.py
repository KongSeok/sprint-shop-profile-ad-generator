"""Pure checks for unsupported numbers and provenance claims."""
import json
import re
import unicodedata

ORIGIN_GRADE_WORDS = ('국내산', '국산', '수입', '미국산', '호주산', '캐나다산', '칠레산', '스페인산', '중국산', '한우', '한돈', '1++', '1+', '투플', '유기농', '무농약', '친환경', '제주산')
NUMBER_PATTERN = re.compile(r'\d[\d,]*(?:\.\d+)?(?:\s*[억만천백십](?:\s*\d[\d,]*(?:\.\d+)?)*[억만천백십]?)*')
UNITS = {'십': 10, '백': 100, '천': 1000, '만': 10000, '억': 100000000}


def number_tokens(text: str) -> list[tuple[str, str]]:
    from decimal import Decimal
    result = []
    for match in NUMBER_PATTERN.finditer(unicodedata.normalize('NFKC', text)):
        raw = match.group()
        value = raw.replace(',', '').replace(' ', '')
        section = Decimal(0)
        total = Decimal(0)
        current = Decimal(0)
        for token in re.findall(r'\d+(?:\.\d+)?|[억만천백십]', value):
            if token not in UNITS:
                current = Decimal(token)
            elif UNITS[token] < 10000:
                section += (current or 1) * UNITS[token]
                current = Decimal(0)
            else:
                total += (section + current or 1) * UNITS[token]
                section = current = Decimal(0)
        normalized = format(total + section + current, 'f').rstrip('0').rstrip('.') if '.' in format(total + section + current, 'f') else str(total + section + current)
        result.append((raw, normalized))
    return result


def output_text(generated) -> str:
    return '\n'.join([generated.instagram.body, *generated.instagram.hashtags, generated.delivery_app.body, generated.naver_place.body])


def fact_warnings(inputs: str, output: str) -> list[str]:
    known = {value for _, value in number_tokens(inputs)}
    warnings = [f"입력에 없는 숫자 '{raw}'이 들어갔어요" for raw, value in number_tokens(output) if value not in known]
    for word in ORIGIN_GRADE_WORDS:
        pattern = re.escape(word) + (r'(?!\+)' if word == '1+' else '')
        if re.search(pattern, output) and not re.search(pattern, inputs):
            warnings.append(f"입력에 없는 원산지·등급 표현 '{word}'이 들어갔어요")
    return list(dict.fromkeys(warnings))


def merge_warnings(warnings: list[str]) -> list[str]:
    """Keep one warning per offending expression across all checkers."""
    seen, merged = set(), []
    for warning in warnings:
        quoted = re.search(r"'([^']+)'", warning)
        token = quoted.group(1) if quoted else warning.split(': ', 1)[-1]
        identity = unicodedata.normalize('NFKC', token).replace(',', '').strip()
        if identity not in seen:
            seen.add(identity)
            merged.append(warning)
    return merged
