import json
import logging
from random import Random

from pydantic import ValidationError

from app.core import config
from app.schemas.concept import (Concept, ConceptCandidate, ConceptRecommendation, ConceptSuggestions,
                                 ModelSuggestions, allowed_themes, can_suggest)
from app.services.design_options import default_design
from app.services.llm_client import LLMError, QUOTA_MESSAGE, generate_json
from app.services.template_v3 import styles


def auto_concept(profile, source_text) -> Concept | None:
    if not can_suggest(profile):
        return None
    try:
        prompt = (config.PROJECT_ROOT / "app/prompts/concept_auto_v1.txt").read_text(encoding="utf-8")
        prompt += "\n허용 theme 목록: " + json.dumps(allowed_themes(), ensure_ascii=False)
        contents = profile.model_dump(include={
            "shop_name", "business_type", "menus", "owner_phrases", "avoid_expressions", "other_info",
        })
        contents["source_text"] = source_text
        raw = generate_json(prompt, json.dumps(contents, ensure_ascii=False),
                            ConceptCandidate.model_json_schema(), 0.3, "concept_auto")
        candidate = ConceptCandidate.model_validate_json(raw)
        return Concept(**candidate.model_dump(), source="자동")
    except (LLMError, ValueError, OSError) as exc:
        # Error messages may contain source text or credentials. Record only a safe code.
        logging.getLogger(__name__).warning("Automatic concept unavailable (%s)",
                                           exc.code if isinstance(exc, LLMError) else type(exc).__name__)
        return None


def shuffled_options(seed):
    rng = Random(seed)

    def shuffled(items):
        items = list(items)
        rng.shuffle(items)
        return items

    catalog = styles()
    return {style: {
        "label": catalog[style]["label"], "desc": catalog[style].get("desc", ""),
        **{group: {key: catalog[style][group][key]["name"] for key in shuffled(catalog[style][group])}
           for group in ("palettes", "fonts")},
    } for style in shuffled(catalog)}


def apply_price_rules(candidates, profile, menu_name, suggest_original):
    selected = next((menu for menu in profile.menus or [] if menu.name == menu_name), None)
    has_price = bool(selected and (selected.price or "").strip())
    menus = profile.menus or []
    enough_prices = bool(menus) and 2 * sum(bool((menu.price or "").strip()) for menu in menus) >= len(menus)
    logger = logging.getLogger(__name__)
    for item in candidates:
        design = item.design
        if design.ad_layout == "big_price" and not has_price:
            design.ad_layout = "photo_full" if suggest_original else "cutout_studio"
            logger.warning("Price rule replaced big_price ad layout with %s", design.ad_layout)
        if design.menu_layout == "big_price" and not enough_prices:
            design.menu_layout = "text_list"
            logger.warning("Price rule replaced big_price menu layout with text_list")
    if len({item.design.ad_layout for item in candidates}) < 2:
        last = candidates[-1].design
        last.ad_layout = "receipt" if last.ad_layout != "receipt" else "photo_full"
        logger.warning("Price rule restored ad layout diversity")
    return candidates


def suggest_concepts(profile, menu_name=None, *, photo_menu_count=0, suggest_original=False, raise_on_error=False, shop_id=None, concept=None):
    menu_name = menu_name or (profile.menus[0].name if profile.menus else None)
    fallback = fallback_suggestions(profile, menu_name, photo_menu_count=photo_menu_count,
                                    suggest_original=suggest_original)
    prompt = (config.PROJECT_ROOT / "app/prompts/concept_v1.txt").read_text(encoding="utf-8")
    prompt += "\n디자인 규칙: 서로 다른 style의 후보를 3개 고르세요. palette와 font는 해당 style의 키만 쓰세요."
    prompt += "\n이유는 가게 정보에 근거하세요. 언어와 원산지 표시 여부는 사장님이 고릅니다."
    primary = default_design(profile.business_type).style
    prompt += f"\n{primary}을 반드시 포함하고 광고 레이아웃을 최소 2종 고르세요."
    prompt += "\n이유는 분위기, 손님층 또는 메뉴 사실을 넣은 완결된 한 문장으로 쓰세요. '~를 위해.'로 끝내지 마세요."
    if suggest_original:
        prompt += "\ncutout_studio는 제외하세요. receipt와 big_price는 원본 사진을 사용합니다."
    seed = shop_id if shop_id is not None else (profile.shop_name or "") + "|" + (profile.business_type or "")
    prompt += "\n스타일별 옵션: " + json.dumps(shuffled_options(seed), ensure_ascii=False)
    contents = profile.model_dump(include={"shop_name", "business_type", "mood_strengths", "tone"})
    contents["menu_name"] = menu_name
    if concept is not None and can_suggest(profile):
        selected_concept = Concept.model_validate(concept)
        contents["concept"] = selected_concept.model_dump(include={"mood", "tone"})
        prompt += "\n사장님이 고른 컨셉. 사실이 아니니 사실처럼 쓰지 않기"
        prompt += "\n디자인 스타일과 후보 이유도 이 표현 방향에 맞추세요."
    selected = next((menu for menu in profile.menus or [] if menu.name == menu_name), None)
    prompt += "\n가격이 없으면 big_price를 고르지 마. 메뉴판은 가격 있는 메뉴가 절반 이상일 때만 big_price를 고르세요."
    prompt += f"\n선택 메뉴 가격 있음: {bool(selected and (selected.price or '').strip())}; 전체 메뉴 가격 입력 수: {sum(bool((menu.price or '').strip()) for menu in profile.menus or [])}/{len(profile.menus or [])}."

    try:
        raw = generate_json(prompt, json.dumps(contents, ensure_ascii=False),
                            ModelSuggestions.model_json_schema(), 0.9, "concept_design")
    except LLMError as exc:
        if raise_on_error:
            raise
        if exc.code == "insufficient_quota":
            fallback.fallback_reason = QUOTA_MESSAGE
        return fallback
    try:
        data = json.loads(raw)
        rows = data.get("candidates", []) if isinstance(data, dict) else []
    except ValueError:
        return fallback
    if not isinstance(rows, list):
        return fallback
    valid = []
    for row in rows[:3]:
        try:
            candidate = ConceptRecommendation.model_validate(row)
        except ValidationError:
            continue
        if suggest_original and candidate.design.ad_layout == "cutout_studio":
            continue
        if any(candidate.design.style == item.design.style or candidate.name == item.name or
               candidate.mood == item.mood for item in valid):
            continue
        valid.append(candidate)
    repaired = len(valid) != 3
    if not any(item.design.style == primary for item in valid):
        valid = [fallback.candidates[0], *valid[:2]]
        repaired = True
    for candidate in fallback.candidates:
        if len(valid) == 3:
            break
        if all(candidate.design.style != item.design.style and candidate.name != item.name
               and candidate.mood != item.mood for item in valid):
            valid.append(candidate)
    if len(valid) != 3:
        valid = fallback.candidates
        repaired = True
    if len({item.design.ad_layout for item in valid}) < 2:
        layout = "receipt" if valid[-1].design.ad_layout != "receipt" else "big_price"
        valid[-1].design.ad_layout = layout
        repaired = True
    default_used = repaired
    subject = menu_name or profile.business_type or "가게 메뉴"
    for item in valid:
        reason = item.design.reason.strip()
        if (not reason.endswith((".", "!", "?")) or reason.endswith("위해.")
                or not (subject in reason or (profile.mood_strengths and profile.mood_strengths in reason))):
            item.design.reason = f"{subject[:60]} 소개에 어울리도록 {styles()[item.design.style]['label']} 스타일을 골랐습니다."
            repaired = True
    if repaired:
        logging.getLogger(__name__).warning("Design candidates repaired without an LLM retry (shop_id=%s)", shop_id)
    apply_price_rules(valid, profile, menu_name, suggest_original)
    return ConceptSuggestions(candidates=valid, source="기본" if default_used else "추천")


def fallback_suggestions(profile, menu_name=None, *, photo_menu_count=0, suggest_original=False):
    primary = default_design(profile.business_type).style
    ordered = [primary, *(style for style in styles() if style != primary)]
    candidates = []
    for index, style in enumerate(ordered[:3]):
        design = default_design(profile.business_type, style).model_dump(exclude={"lang", "show_origin", "source"})
        design["ad_layout"] = ("photo_full", "receipt" if suggest_original else "cutout_studio", "big_price")[index]
        subject = menu_name or (profile.menus[0].name if profile.menus else profile.business_type) or "가게 메뉴"
        design["reason"] = f"{subject[:60]} 소개에 어울리도록 {styles()[style]['label']} 스타일을 골랐습니다."
        if index == 2 and photo_menu_count:
            design["menu_layout"] = "premium"
        candidates.append(dict(name=f"기본 디자인 {index + 1}", mood=f"{style} 분위기",
                               tone="친근한 존댓말", design=design))
    result = ConceptSuggestions(candidates=candidates, source="기본")
    apply_price_rules(result.candidates, profile, subject, suggest_original)
    return result
