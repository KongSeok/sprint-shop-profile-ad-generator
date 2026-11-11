import base64
import binascii

from time import perf_counter

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from app.core.config import CUTOUT_MAX_UPLOAD_BYTES
from app.schemas.profile import ProfileModel
from app.services import compose, cutout, image_models
from app.core import config
from app.api.routers.render import resolve_profile
from app.schemas.image import BackgroundRequest, BackgroundResponse, ComposeRequest, ComposeResponse


router = APIRouter(prefix="/image", tags=["image"])


class CutoutRequest(ProfileModel):
    photo_base64: str = Field(min_length=1, max_length=4 * ((CUTOUT_MAX_UPLOAD_BYTES + 2) // 3))


class CutoutResponse(ProfileModel):
    suggest_original: bool
    reason: str | None
    foreground_ratio: float
    partial_foreground_ratio: float
    original_png_base64: str
    cutout_png_base64: str


@router.post("/cutout", response_model=CutoutResponse)
def create_cutout(request: CutoutRequest):
    try:
        data = base64.b64decode(request.photo_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "사진의 base64 형식을 확인해 주세요.") from exc
    try:
        return cutout.create_cutout(data)
    except cutout.InvalidPhoto as exc:
        raise HTTPException(422, str(exc)) from exc
    except cutout.CutoutUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc



def encode(data):
    return base64.b64encode(data).decode("ascii")


def decode(data):
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "사진의 base64 형식을 확인해 주세요.") from exc


def background_model(http):
    if not config.IMAGE_ENABLED:
        raise HTTPException(503, image_models.DISABLED)
    model = getattr(http.app.state, "background_model", None)
    if model is None:
        raise HTTPException(503, "이미지 모델을 불러오지 못했어요. 사진 그대로를 써 주세요.")
    return model


@router.post("/background", response_model=BackgroundResponse)
def create_background(request: BackgroundRequest, http: Request):
    model = background_model(http)
    profile = resolve_profile(request)
    try:
        result = image_models.generate_empty_background(model, profile, request.seed, request.steps)
    except image_models.ImageUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return BackgroundResponse(
        png_base64=encode(result.png), seed=result.seed, prompt=result.prompt,
        negative_prompt=result.negative_prompt, seconds=result.seconds, max_vram_mb=result.max_vram_mb,
    )


@router.post("/compose", response_model=ComposeResponse)
def create_composition(request: ComposeRequest, http: Request):
    if request.mode == "cutout" and not config.IMAGE_ENABLED:
        raise HTTPException(503, image_models.DISABLED)
    model = background_model(http) if request.mode == "cutout" and request.background_png_base64 is None else None
    profile = resolve_profile(request)
    background = request.background_png_base64 if request.mode == "cutout" else None
    seed = request.seed if request.mode == "cutout" else None
    background_seconds = 0.0
    try:
        if model is not None:
            generated = image_models.generate_empty_background(model, profile, seed)
            background, seed, background_seconds = encode(generated.png), generated.seed, generated.seconds
        started = perf_counter()
        if request.mode == "original":
            result = compose.compose_original(decode(request.photo_base64))
        else:
            result = compose.compose_cutout(decode(request.cutout_png_base64), decode(background))
        compose_seconds = perf_counter() - started
    except compose.InvalidComposition as exc:
        raise HTTPException(422, str(exc)) from exc
    except image_models.ImageUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return ComposeResponse(
        composite_png_base64=encode(result.png), background_png_base64=background, seed=seed,
        food_bbox=result.food_bbox,
        food_mask_png_base64=encode(result.food_mask_png) if result.food_mask_png else None,
        seconds={"background": background_seconds, "compose": compose_seconds},
    )
