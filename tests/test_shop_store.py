import pytest

from app.schemas.profile import ShopProfile
from app.services import shop_store


def test_save_update_list_get_and_persistence(tmp_path):
    db = tmp_path / "nested/shops.db"
    shop_store.init_db(db)
    shop_store.init_db(db)
    assert shop_store.list_shops(db_path=db) == []
    profile = ShopProfile(shop_name=" 우리 가게 ", business_type=" 카페 ",
                          other_info=[" 국내산 ", " "], parking=" ", menus=[])
    shop_id = shop_store.save_shop(profile, " 원문 ", "v2", db_path=db)
    saved = shop_store.get_shop(shop_id, db_path=db)
    assert saved["profile"]["shop_name"] == "우리 가게"
    assert saved["profile"]["parking"] is None
    assert saved["profile"]["menus"] is None
    assert saved["profile"]["other_info"] == ["국내산"]
    assert saved["source_text"] == " 원문 "
    updated = profile.model_copy(update={"shop_name": "다른 이름"})
    assert shop_store.save_shop(updated, "수정 원문", "v1", shop_id, db_path=db) == shop_id
    latest = shop_store.get_shop(shop_id, db_path=db)
    assert latest["created_at"] == saved["created_at"]
    assert latest["updated_at"] >= saved["updated_at"]
    assert latest["profile"]["shop_name"] == "다른 이름"
    assert shop_store.list_shops(db_path=db) == [{
        "id": shop_id, "shop_name": "다른 이름", "business_type": "카페", "updated_at": latest["updated_at"],
    }]
    with pytest.raises(LookupError):
        shop_store.get_shop(999, db_path=db)
    with pytest.raises(LookupError):
        shop_store.save_shop(updated, "", "v2", 999, db_path=db)
    assert len(shop_store.list_shops(db_path=db)) == 1


def test_store_also_rejects_blank_identity(tmp_path):
    db = tmp_path / "shops.db"
    shop_store.init_db(db)
    with pytest.raises(ValueError, match="가게 이름과 업종"):
        shop_store.save_shop(ShopProfile(shop_name=None, business_type=" "), "", "v2", db_path=db)
