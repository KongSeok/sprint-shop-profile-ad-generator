import pytest

from app.ui.profile_form import blank_to_none, form_to_profile, lines_to_list, list_to_lines, table_to_menus


def test_lines_and_blank_values():
    assert lines_to_list("  국내산  \n\n 예약 가능 \n") == ["국내산", "예약 가능"]
    assert list_to_lines([" 국내산 ", " ", "예약 가능"]) == "국내산\n예약 가능"
    assert lines_to_list(list_to_lines(None)) is None
    assert blank_to_none(" \n ") is None
    assert blank_to_none(float("nan")) is None
    assert blank_to_none("  17,000원 ") == "17,000원"


def test_table_to_menus_ignores_empty_rows_and_keeps_nullable_price():
    assert table_to_menus([
        {"name": " 라떼 ", "price": " "}, {"name": "", "price": None},
        {"name": " 아메리카노 ", "price": " 4천원 "},
    ]) == [{"name": "라떼", "price": None}, {"name": "아메리카노", "price": "4천원"}]
    assert table_to_menus([]) is None
    with pytest.raises(ValueError, match="메뉴 이름"):
        table_to_menus([{"name": "", "price": "4천원"}])


def test_empty_form_stays_null_and_source_values_are_trimmed():
    empty = form_to_profile({}, [])
    assert all(value is None for value in empty.values())
    values = form_to_profile({"shop_name": " 우리 가게 ", "other_info": " 국내산 \n"}, [], [" 확인 필요 "])
    assert values["shop_name"] == "우리 가게"
    assert values["other_info"] == ["국내산"]
    assert values["needs_check"] == ["확인 필요"]
