import pytest
from app.services.fact_check import fact_warnings, number_tokens


@pytest.mark.parametrize('inputs,output', [('13,000원', '13000원'), ('1만 3천원', '13000원'), ('13000원', '1만 3천원'), ('국내산', '국내산')])
def test_supported(inputs, output):
    assert fact_warnings(inputs, output) == []


def test_unknown_numbers_origin_and_hashtags():
    warnings = fact_warnings('미국산 13000원', '국내산 15000원 #20개')
    assert "입력에 없는 숫자 '15000'이 들어갔어요" in warnings
    assert "입력에 없는 숫자 '20'이 들어갔어요" in warnings
    assert "입력에 없는 원산지·등급 표현 '국내산'이 들어갔어요" in warnings


def test_grade_specific_and_no_duplicate():
    assert len(fact_warnings('1+', '1++ 1++')) == 1
    assert fact_warnings('1++', '1+')


def test_raw_spelling():
    assert number_tokens('1만 3천원 13,000원') == [('1만 3천', '13000'), ('13,000', '13000')]
