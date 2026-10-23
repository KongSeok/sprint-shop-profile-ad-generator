import pytest


def payload(**profile_changes):
    return {"shop_id": None, "profile": {"shop_name": " 테스트 ", "business_type": " 카페 ", **profile_changes},
            "source_text": "저희 가게 소개입니다", "prompt_version": "v2"}


def test_save_list_get_then_update_same_id(api_client, gemini_mock):
    assert api_client.get("/profile/list").json() == []
    request = payload(parking=" ", other_info=[" 국내산 ", ""], menus=[])
    response = api_client.post("/profile/save", json=request)
    assert response.status_code == 200
    shop_id = response.json()["shop_id"]
    assert api_client.get("/profile/list").json()[0]["id"] == shop_id
    saved = api_client.get(f"/profile/{shop_id}").json()
    assert saved["source_text"] == request["source_text"]
    assert saved["profile"]["parking"] is None and saved["profile"]["menus"] is None
    assert saved["profile"]["other_info"] == ["국내산"]
    request["shop_id"] = shop_id
    request["profile"]["shop_name"] = "수정 가게"
    assert api_client.post("/profile/save", json=request).json() == {"shop_id": shop_id}
    assert len(api_client.get("/profile/list").json()) == 1
    assert api_client.get(f"/profile/{shop_id}").json()["profile"]["shop_name"] == "수정 가게"
    gemini_mock.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"shop_name": None}, {"shop_name": " \n"}, {"business_type": None}, {"business_type": " "},
])
def test_save_requires_identity_but_extract_stays_nullable(api_client, changes):
    response = api_client.post("/profile/save", json=payload(**changes))
    assert response.status_code == 422
    assert "가게 이름과 업종은 꼭 적어 주세요" in response.text
    assert api_client.get("/profile/list").json() == []
    response = api_client.post("/profile/extract", json={"text": "소개", "prompt_version": "v1"})
    assert response.status_code == 200 and response.json()["shop_name"] is None


def test_save_missing_identity_key_and_unknown_id(api_client):
    request = payload()
    del request["profile"]["shop_name"]
    assert api_client.post("/profile/save", json=request).status_code == 422
    assert api_client.get("/profile/999").status_code == 404
    request = payload()
    request["shop_id"] = 999
    assert api_client.post("/profile/save", json=request).status_code == 404
    assert api_client.get("/profile/list").json() == []


def test_price_without_menu_name_is_rejected(api_client):
    assert api_client.post("/profile/save", json=payload(menus=[{"name": " ", "price": "5000원"}])).status_code == 422
