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


def test_overlapping_checkers_report_expression_once():
    from app.services.fact_check import merge_warnings
    assert merge_warnings(["예시 내용이 섞였어요: 15,000", "입력에 없는 숫자 '15000'이 들어갔어요"]) == ["예시 내용이 섞였어요: 15,000"]


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_generator_runs_fact_checks_for_both_versions(gemini_mock, version):
    import json
    from app.schemas.profile import ShopProfile
    from app.schemas.copy import CopyMenu
    from app.services.copy_generator import generate_copy
    generated = {'instagram': {'body': '국내산 메뉴입니다.\n15000원에 만나요.\n오늘도 기다릴게요.', 'hashtags': ['#메뉴', '#소개', '#식사', '#오늘', '#가게']}, 'delivery_app': {'body': '메뉴 소개.'}, 'naver_place': {'body': '소개합니다. 편히 오세요. 기다릴게요.'}}
    gemini_mock.return_value.__enter__.return_value.models.generate_content.return_value.text = json.dumps(generated)
    result = generate_copy(ShopProfile(shop_name=None, business_type=None), CopyMenu(name='라떼'), version)
    assert any('15000' in warning for warning in result.warnings)
    assert any('국내산' in warning for warning in result.warnings)
