import base64
import sqlite3
from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from app.schemas.profile import ShopProfile
from app.schemas.render import AdCardRequest, MenuBoardRequest, RenderResponse
from app.services import renderer, shop_store

router = APIRouter(prefix='/render', tags=['render'])


def resolve_profile(request):
    if request.profile is not None:
        return request.profile
    try:
        return ShopProfile.model_validate(shop_store.get_shop(request.shop_id)['profile'])
    except LookupError as exc:
        raise HTTPException(404, '저장된 가게를 찾을 수 없습니다') from exc
    except (sqlite3.Error, OSError, ValidationError) as exc:
        raise HTTPException(503, '가게 정보를 읽지 못했어요') from exc


def response(result):
    return RenderResponse(png_base64=base64.b64encode(result.png).decode(), warnings=result.warnings)


@router.post('/ad-card', response_model=RenderResponse)
def ad_card(request: AdCardRequest):
    profile = resolve_profile(request)
    try:
        return response(renderer.render_ad_card(profile, request.menu, {'headline': request.headline, 'body': request.body}, request.template, request.theme))
    except renderer.RenderError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/menu-board', response_model=RenderResponse)
def menu_board(request: MenuBoardRequest):
    profile = resolve_profile(request)
    try:
        return response(renderer.render_menu_board(profile, request.menus, request.template, request.theme))
    except renderer.RenderError as exc:
        raise HTTPException(422, str(exc)) from exc
