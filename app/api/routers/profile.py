import sqlite3

from fastapi import APIRouter, HTTPException

from app.schemas.profile import ProfileExtractRequest, ShopProfile
from app.schemas.profile_save import ProfileSaveRequest, ProfileSaveResponse, SavedShop, ShopListItem
from app.services.profile_extractor import ProfileExtractionError, extract_profile
from app.services import shop_store

router = APIRouter(prefix="/profile", tags=["profile"])


@router.post("/extract", response_model=ShopProfile)
def extract(request: ProfileExtractRequest) -> ShopProfile:
    try:
        return extract_profile(request.text, request.prompt_version)
    except ProfileExtractionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post("/save", response_model=ProfileSaveResponse)
def save(request: ProfileSaveRequest):
    try:
        return {"shop_id": shop_store.save_shop(
            request.profile, request.source_text, request.prompt_version, request.shop_id,
        )}
    except LookupError as exc:
        raise HTTPException(404, "저장된 가게를 찾을 수 없습니다") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "저장하지 못했어요. 잠시 후 다시 눌러 주세요") from exc


@router.get("/list", response_model=list[ShopListItem])
def list_saved():
    try:
        return shop_store.list_shops()
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "목록을 불러오지 못했어요. 잠시 후 다시 눌러 주세요") from exc


@router.get("/{shop_id}", response_model=SavedShop)
def get_saved(shop_id: int):
    try:
        return shop_store.get_shop(shop_id)
    except LookupError as exc:
        raise HTTPException(404, "저장된 가게를 찾을 수 없습니다") from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "가게를 불러오지 못했어요. 잠시 후 다시 눌러 주세요") from exc
