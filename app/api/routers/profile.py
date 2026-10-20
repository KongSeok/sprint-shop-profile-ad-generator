from fastapi import APIRouter, HTTPException

from app.schemas.profile import ProfileExtractRequest, ShopProfile
from app.services.profile_extractor import ProfileExtractionError, extract_profile

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
