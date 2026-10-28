"""Deterministic channel examples; metadata never enters the model prompt."""
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


def select_examples(path: Path, business_type: str | None, seed: int = EXAMPLE_SEED) -> list[dict]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    category = business_category(business_type)
    rng = random.Random(seed)
    selected = []
    for channel in CHANNELS:
        candidates = [row for row in rows if row.get('channel') == channel and row.get('text')]
        preferred = [r for r in candidates if category and r.get('business_type') == category]
        others = [r for r in candidates if r not in preferred]
        rng.shuffle(preferred)
        rng.shuffle(others)
        selected.extend((preferred + others)[:3])
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
