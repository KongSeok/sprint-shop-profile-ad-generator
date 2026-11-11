"""Conservative offline checks. Fact detection is a lower bound, not semantic proof."""
import json
import re
from collections import Counter
from types import SimpleNamespace

from pydantic import ValidationError

from app.schemas.copy import GeneratedShopCopy, GeneratedMenuCopy
from app.services.style_check import style_warnings


def instagram_facts(text, profile, menu=None):
    facts = set()
    menus = [m.name for m in profile.menus or []] + ([menu.name] if menu else [])
    for name in set(menus):
        if name and name in text:
            facts.add('메뉴 ' + name)
    for field in ('business_type', 'location', 'hours', 'closed_days', 'parking', 'takeout_delivery'):
        value = getattr(profile, field)
        if value and value in text:
            facts.add(field + ': ' + value)
    for item in profile.menus or []:
        if item.price and item.price in text:
            facts.add('가격 ' + item.price)
    if menu and menu.price and menu.price in text:
        facts.add('가격 ' + menu.price)
    if '숯불' in text and '숯불' in (profile.mood_strengths or ''):
        facts.add('숯불 조리')
    for word in ('에티오피아', '콜롬비아', '과테말라', '국내산', '미국산', '한우', '한돈'):
        if word in text:
            facts.add(word)
    for pattern, fact in ((r'매일.{0,12}(만들|굽|구워)', '매일 생산'),
                          (r'(다음\s*날|이튿날).{0,15}(팔지|판매하지)', '다음 날 재판매 안 함'),
                          (r'동네\s*빵집', 'business_type: 동네 빵집'), (r'대표\s*메뉴', '대표 메뉴')):
        if re.search(pattern, text):
            facts.add(fact)
    return sorted(facts)


def body_texts(data, mode):
    key = 'shop_intro' if mode == 'shop' else 'menu_description'
    result = {'instagram': data['instagram']['body'], 'delivery_app': data['delivery_app'][key]}
    if mode == 'shop':
        result['naver_place'] = data['naver_place']['body']
    return result


def inspect_copy(raw, mode, profile, menu=None):
    issues = []
    try:
        data = json.loads(raw)
        texts = body_texts(data, mode)
        assert all(isinstance(v, str) and v.strip() for v in texts.values())
        tags = data['instagram']['hashtags']
        assert isinstance(tags, list) and all(isinstance(t, str) for t in tags)
    except (ValueError, KeyError, TypeError, AssertionError):
        return None, ['format: JSON 형식 또는 필수 출력 칸이 잘못됐어요']
    model = GeneratedShopCopy if mode == 'shop' else GeneratedMenuCopy
    try:
        model.model_validate(data)
    except ValidationError as exc:
        for error in exc.errors(include_input=False):
            issues.append('schema: ' + '.'.join(map(str, error['loc'])) + ' ' + error['msg'])
    for channel, text in texts.items():
        if re.search(r'\b(remove|maybe|todo|fixme|rewrite|note|edit|delete)\b', text, re.I) or re.search(r'[（(][^）)]*(수정|삭제|대안|메모|확인)[^）)]*[）)]', text):
            issues.append(f'editing_note: {channel} 편집 메모를 지우세요')
        if re.search(r'\?\s*[^\w가-힣\s]{2,}', text):
            issues.append(f'odd_tail: {channel} 물음표 뒤 이모지 꼬리를 지우세요')
        for banned in profile.avoid_expressions or []:
            if banned and banned in text:
                issues.append(f'banned: {channel} 금지 표현 {banned}')
        # Count lexical stems after common particles; do not count function words.
        tokens = re.findall(r'[가-힣A-Za-z]{2,}', text)
        stems = [re.sub(r'(에서는|으로는|에서|으로|처럼|까지|부터|하고|에는|이랑|과|와|은|는|을|를|이|가|의|에|도)$', '', t) for t in tokens]
        for word, count in Counter(stems).items():
            if len(word) >= 2 and count >= 3 and word not in ('있어요', '좋아요', '그리고', '함께', '하는'):
                issues.append(f'repetition: {channel} {word} {count}회')
        if channel != 'instagram' and len(re.findall(r'[가-힣]+(?:입니다|습니다)[.!?]?', text)) > 1:
            issues.append(f'tone: {channel} ~습니다/~입니다 두 문장 이상')
    adapted = SimpleNamespace(delivery_app=SimpleNamespace(body=texts['delivery_app']),
                              naver_place=SimpleNamespace(body=texts.get('naver_place', '')))
    issues.extend('banned_style: ' + warning for warning in style_warnings(adapted))
    for banned in profile.avoid_expressions or []:
        if banned and any(banned in tag for tag in tags):
            issues.append('banned: 해시태그 ' + banned)
    facts = instagram_facts(texts['instagram'], profile, menu)
    if len(facts) > 2:
        issues.append('facts: 인스타 본문 사실 최대 2개 초과: ' + ', '.join(facts))
    if any(tag in texts['instagram'] for tag in tags if tag):
        issues.append('hashtags: 본문에서 해시태그를 빼세요')
    if mode == 'menu':
        delivery = texts['delivery_app']
        if profile.shop_name and profile.shop_name in delivery:
            issues.append('menu_only: 배달앱 메뉴 설명에서 가게명을 빼세요')
        if re.search(r'매일.{0,12}(만들|굽)|동네\s*빵집|영업시간|좌석|휴무', delivery):
            issues.append('menu_only: 배달앱 메뉴 설명에서 가게 소개를 빼세요')
        senses = sum(bool(re.search(pattern, delivery)) for pattern in
                     (r'향|냄새', r'식감|쫄깃|바삭|부드|결|촉촉|쫀득', r'소리|지글|바삭', r'따뜻|뜨거|차가|시원|온기|온도'))
        from app.services.fact_check import ORIGIN_PATTERN, assorted_menu, component_warnings
        if ORIGIN_PATTERN.search(delivery):
            issues.append('origin: 메뉴 설명에서 원산지 표현을 빼세요')
        issues.extend(component_warnings(menu, delivery))
        if senses < 2 and not (assorted_menu(menu) and menu.components):
            issues.append('sensory: 메뉴 설명에 향·식감·소리·온도 중 두 종류 이상 쓰세요')
    count = len([s for s in re.split(r'[.!?]+(?:\s|$)', texts['delivery_app']) if s.strip()])
    invalid_count = count != 2 if mode == 'menu' else not 2 <= count <= 3
    if invalid_count:
        issues.append('sentences: 배달앱 문장 수를 맞춰 주세요')
    if mode == 'shop':
        blocks = texts['naver_place'].split('\n\n')
        if len(blocks) not in (2, 3) or len(blocks[0].splitlines()) != 1 or not 3 <= len(blocks[1].splitlines()) <= 4:
            issues.append('place_format: 헤드라인·빈 줄·소개 3~4줄·정보 줄 형식을 맞춰 주세요')
    for phrase in profile.owner_phrases or []:
        if phrase and sum(text.count(phrase) for text in texts.values()) > 1:
            issues.append('owner_phrase: 사장님 꾸밈말은 전체 한 번만 쓰세요')
    return data, list(dict.fromkeys(issues))
