import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from app.schemas.copy import CopyGenerateRequest, CopyGenerateResponse
from app.schemas.profile import ShopProfile
from app.services import shop_store
from app.services.copy_generator import CopyGenerationError, generate_copy

router = APIRouter(prefix="/copy", tags=["copy"])


@router.post("/generate", response_model=CopyGenerateResponse)
def generate(request: CopyGenerateRequest):
    profile = request.profile
    concept = request.concept
    if request.shop_id is not None:
        try:
            saved = shop_store.get_shop(request.shop_id)
            profile = ShopProfile.model_validate(saved["profile"])
            concept = saved.get("concept")
        except LookupError as exc:
            raise HTTPException(404, "저장된 가게를 찾을 수 없습니다") from exc
        except (sqlite3.Error, OSError, ValidationError) as exc:
            raise HTTPException(503, "가게 정보를 읽지 못했어요. 잠시 후 다시 눌러 주세요") from exc
    try:
        return generate_copy(profile, request.menu, request.prompt_version, concept=concept)
    except CopyGenerationError as exc:
        raise HTTPException(exc.status_code, detail={
            "code": exc.code, "message": str(exc), "upstream_status": exc.upstream_status,
        }) from exc
