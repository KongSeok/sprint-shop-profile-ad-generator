import re

from app.services.fact_check import ORIGIN_PATTERN


# Try shorter units first so runs such as "요요요요" collapse to one character.
REPEATED_TEXT = re.compile(r"([가-힣A-Za-z]{1,4}?)\1{2,}")


def repeated_copy_fields(data):
    if not isinstance(data, dict):
        return []
    repeated = []
    for field, value in data.items():
        if isinstance(value, str) and REPEATED_TEXT.search(value):
            repeated.append(field)
        elif isinstance(value, dict):
            repeated.extend(f"{field}.{key}" for key in repeated_copy_fields(value))
        elif isinstance(value, list) and any(isinstance(item, str) and REPEATED_TEXT.search(item) for item in value):
            repeated.append(field)
    return repeated


def trim_repeated_copy(value):
    if isinstance(value, dict):
        return {key: trim_repeated_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [trim_repeated_copy(item) for item in value]
    if isinstance(value, str):
        while REPEATED_TEXT.search(value):
            value = REPEATED_TEXT.sub(r"\1", value)
    return value


def ad_copy(generated):
    delivery = generated.get('delivery_app') or {}
    body = delivery.get('menu_description') or ''
    if ORIGIN_PATTERN.search(body):
        body = ' '.join(part for part in re.split(r'(?<=[.!?])\s+|\n+', body)
                        if not ORIGIN_PATTERN.search(part))
    return {'body': body, 'menu_name_en': generated.get('menu_name_en')}
