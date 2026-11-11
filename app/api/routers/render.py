import base64
import sqlite3
from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from app.schemas.design import SavedDesign
from app.schemas.profile import ShopProfile
from app.schemas.render import AdCardRequest, MenuBoardRequest, RenderResponse
from app.services import menu_translation, renderer, shop_store
from app.services.llm_client import LLMError, QUOTA_MESSAGE

router = APIRouter(prefix='/render', tags=['render'])


def resolve_source(request):
    if request.profile is not None:
        return request.profile, None
    try:
        shop = shop_store.get_shop(request.shop_id)
        return ShopProfile.model_validate(shop['profile']), shop.get('design')
    except LookupError as exc:
        raise HTTPException(404, '저장된 가게를 찾을 수 없습니다') from exc
    except (sqlite3.Error, OSError, ValidationError) as exc:
        raise HTTPException(503, '가게 정보를 읽지 못했어요') from exc


def resolve_profile(request):
    return resolve_source(request)[0]


def resolve_design(request, saved):
    if request.design is not None:
        return request.design
    if saved is not None:
        try:
            return SavedDesign.model_validate(saved)
        except ValidationError:
            return None
    return None


def response(result):
    return RenderResponse(png_base64=base64.b64encode(result.png).decode(), warnings=result.warnings)


@router.post('/ad-card', response_model=RenderResponse)
def ad_card(request: AdCardRequest):
    profile, saved = resolve_source(request)
    if not ((request.photo_url or "").strip() or (request.cutout_url or "").strip()):
        raise HTTPException(422, "메뉴 사진을 올려 주세요")
    design = resolve_design(request, saved)
    values = request.model_dump(include={'headline', 'body', 'photo_url', 'background_url', 'food_mask_url', 'suggest_original', 'cutout_url', 'menu_name_en', 'origin'})
    if request.shop_id and not values["origin"] and design and design.show_origin:
        values["origin"] = shop_store.get_shop(request.shop_id)["menu_origins"].get(request.menu.name)
    try:
        return response(renderer.render_ad_card(profile, request.menu, values,
                                                request.template if design is None else None, request.theme, design))
    except renderer.RenderError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/menu-board', response_model=RenderResponse)
def menu_board(request: MenuBoardRequest):
    profile, saved = resolve_source(request)
    design = resolve_design(request, saved)
    try:
        menus = request.menus
        translation_warning = None
        if request.shop_id and design and design.show_origin:
            origins = shop_store.get_shop(request.shop_id)["menu_origins"]
            menus = [dict(menu.model_dump(), origin=getattr(menu, "origin", None) or origins.get(menu.name))
                     for menu in menus or profile.menus or []]
        if request.shop_id and design and design.lang != 'ko':
            shop = shop_store.get_shop(request.shop_id)
            names = list(dict.fromkeys(menu.name for menu in profile.menus or []))
            translations = shop['menu_names_en']
            missing = [name for name in names if name not in translations]
            if missing:
                try:
                    translations.update(menu_translation.translate(missing))
                    shop_store.save_menu_names_en(request.shop_id, shop['profile'], translations)
                except LLMError as exc:
                    translation_warning = QUOTA_MESSAGE if exc.code == 'insufficient_quota' else '영어 메뉴명을 만들지 못했어요. 한글로 표시합니다.'
                except ValueError:
                    translation_warning = '영어 메뉴명을 확인하지 못했어요. 한글로 표시합니다.'
            rows = [menu if isinstance(menu, dict) else menu.model_dump() for menu in menus or profile.menus or []]
            menus = [dict(menu, name_en=menu.get('name_en') or translations.get(menu['name'])) for menu in rows]
        result = renderer.render_menu_board(profile, menus,
                                                  request.template if design is None else None, request.theme, design)
        if translation_warning:
            result.warnings.append(translation_warning)
        return response(result)
    except renderer.RenderError as exc:
        raise HTTPException(422, str(exc)) from exc
