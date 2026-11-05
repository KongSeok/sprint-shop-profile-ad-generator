"""Versioned channel examples; metadata never enters the model prompt."""
import json
import random
import re
from pathlib import Path

CHANNELS = ("instagram", "delivery_app", "naver_place")
EXAMPLE_SEED = 20261028


def business_category(value: str | None) -> str | None:
    for words, category in ((('빵', '베이커리'), '빵집'), (('카페',), '카페'),
                            (('고깃집', '고기', '갈비', '삼겹', '돼지', '소'), '고깃집'),
                            (('우동', '초밥', '라멘', '일식', '일본'), '일식'),
                            (('한식', '백반', '국밥'), '한식'), (('분식',), '분식')):
        if any(word in (value or '') for word in words):
            return category
    return None


def select_examples(path: Path, business_type: str | None, seed: int | None = None, *, example_version: str = 'short-v1', mode: str | None = None) -> list[dict]:
    if example_version not in ('short-v1', 'full-v2', 'full-v3'):
        raise ValueError('알 수 없는 예시 선택 버전입니다')
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    category = business_category(business_type)
    legacy_seed = EXAMPLE_SEED if seed is None or example_version == "full-v3" else seed
    rng = random.Random(legacy_seed)
    selected = []
    for channel in CHANNELS:
        candidates = [row for row in rows if row.get('channel') == channel and row.get('text')
                      and (channel != 'instagram' or row.get('kind', 'short') == 'short')]
        preferred = [r for r in candidates if category and r.get('business_type') == category]
        others = [r for r in candidates if r not in preferred]
        rng.shuffle(preferred)
        rng.shuffle(others)
        selected.extend((preferred + others)[:3])
    if example_version in ('full-v2', 'full-v3'):
        # Separate RNG preserves delivery/place selections, including their shuffle order.
        rng = random.Random(seed if example_version == "full-v3" else legacy_seed)
        full = [r for r in rows if r.get('channel') == 'instagram' and r.get('kind') == 'full'
                and r.get('text') and r.get('style')]
        preferred = [r for r in full if category and r.get('business_type') == category]
        others = [r for r in full if r not in preferred]
        rng.shuffle(preferred)
        rng.shuffle(others)
        if mode in ('shop', 'menu'):
            shop_styles = ('정중한 소개형', '계절 인사 · 가게 이야기', '준비 과정 · 사장님 일상')
            def priority(row):
                is_shop = any(style in row['style'] for style in shop_styles)
                return is_shop if mode == 'shop' else not is_shop
            preferred.sort(key=lambda row: not priority(row))
            others.sort(key=lambda row: not priority(row))
        instagram, styles = [], set()
        for row in preferred + others:
            if row['style'] not in styles:
                instagram.append(row)
                styles.add(row['style'])
                if len(instagram) == 2:
                    break
        short = [r for r in rows if r.get('channel') == 'instagram' and r.get('kind') == 'short'
                 and r.get('text') and category and r.get('business_type') == category]
        rng.shuffle(short)
        selected = instagram + short[:1] + [r for r in selected if r['channel'] != 'instagram']
    return selected


def example_warnings(examples: list[dict], inputs: str, output: str) -> list[str]:
    from app.services.fact_check import number_tokens
    known = {value for _, value in number_tokens(inputs)}
    example_numbers = {value for row in examples for _, value in number_tokens(row['text'])} - known
    leaks = [raw for raw, value in number_tokens(output) if value in example_numbers]
    # Example files contain prose, not structured menus. Detect explicit menu metadata
    # when supplied and food-name tokens with common menu suffixes in the actual text.
    menu_pattern = r'[가-힣]*(?:삼겹살|갈매기살|갈비살|갈비|등심|항정살|라떼|아메리카노|우동|초밥|라멘|국밥|떡볶이|크루아상|소금빵|케이크|빙수|파스타|피자)'
    for row in examples:
        names = row.get('menu_names', []) + re.findall(menu_pattern, row['text'])
        for name in names:
            if name not in inputs and name in output:
                leaks.append(name)
    return [f"예시 내용이 섞였어요: {value}" for value in dict.fromkeys(leaks)]
