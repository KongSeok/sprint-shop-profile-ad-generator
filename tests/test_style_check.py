import json
from types import SimpleNamespace

import pytest

from app.services.style_check import PRESS_RELEASE_EXPRESSIONS, style_warnings
from test_copy import copy_mock, copy_output


def generated(delivery='', place='', instagram=''):
    return SimpleNamespace(delivery_app=SimpleNamespace(body=delivery),
                           naver_place=SimpleNamespace(body=place),
                           instagram=SimpleNamespace(body=instagram))


@pytest.mark.parametrize('expression', PRESS_RELEASE_EXPRESSIONS)
def test_banned_press_word_is_reported(expression):
    warnings = style_warnings(generated(delivery=expression))
    assert len(warnings) == 1 and expression in warnings[0]


@pytest.mark.parametrize('expression', ['선보이는', '갖췄어요', '돋보이는', '살리는', '입맛을 당기는'])
def test_inflected_press_words_are_reported(expression):
    assert style_warnings(generated(place=expression))


def test_instagram_is_not_subject_to_channel_specific_word_ban():
    assert style_warnings(generated(instagram='매력 풍미')) == []
    assert style_warnings(generated(delivery='소갈비살 한 점, 편안한 저녁이에요.')) == []


def test_v2_mock_response_includes_style_warning(api_client, copy_mock, copy_output):
    copy_output['delivery_app']['body'] = '매력 ' + copy_output['delivery_app']['body']
    copy_mock.models.generate_content.return_value.text = json.dumps(copy_output)
    result = api_client.post('/copy/generate', json={"mode": "menu",
        'profile': {'shop_name': None, 'business_type': None}, 'menu': {'name': '라떼'},
    })
    assert result.status_code == 200
    assert any("금지 표현 '매력'" in item for item in result.json()['warnings'])
