"""Render five sample shops and three design candidates per shop."""
import argparse
import base64
import csv
from collections import Counter
import json
from io import BytesIO
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

from app.core.config import GEMINI_API_KEY, LLM_PROVIDER, OPENAI_API_KEY, PROJECT_ROOT
from app.schemas.copy import CopyMenu
from app.schemas.design import DesignCandidate
from app.services.ad_copy import ad_copy
from app.services.copy_generator import CopyGenerationError
from app.services.copy_pipeline import generate_mode_copy
from app.services.cutout import create_cutout, CutoutUnavailable
from app.schemas.profile import ShopProfile
from app.services.compose import compose_cutout, compose_original
from app.services.concept_suggester import fallback_suggestions, suggest_concepts
from app.services.copy_examples import business_category
from app.services.image_models import empty_background
from app.services.renderer import menu_board_layout, open_browser, render_ad_card, render_menu_board
from tools.image_samples import photos

CATEGORIES = {'고깃집': 'meat', '빵집': 'bakery', '카페': 'cafe', '한식': 'korean', '일식': 'japanese'}
PHOTO_MENUS = {
    'meat': ('삼겹살', '삼겹살', '갈비'),
    'bakery': ('바게트', '바게트', '크루아상'),
    'cafe': ('라테', '바스크', '치즈케이크'),
    'korean': ('된장', '불고기', '김치찌개'),
    'japanese': ('초밥', '라멘', '연어 롤'),
}


def sample_shops(available_photos):
    ranked = {}
    path = PROJECT_ROOT / 'data/samples/answer_profiles_gold.jsonl'
    for line in path.read_text(encoding='utf-8').splitlines():
        profile = ShopProfile.model_validate(json.loads(line)['profile'])
        category = business_category(profile.business_type)
        if category not in CATEGORIES or not profile.menus:
            continue
        prefix = CATEGORIES[category]
        for stem, photo in available_photos.items():
            if not stem.startswith(prefix + '_'):
                continue
            index = int(stem.split('_')[1]) - 1
            keyword = PHOTO_MENUS[prefix][index]
            for menu in profile.menus:
                if keyword in menu.name.replace('라떼', '라테').replace('연어롤', '연어 롤'):
                    score = (sum(bool(item.price) for item in profile.menus), len(profile.menus), index == 0)
                    if category not in ranked or score > ranked[category][0]:
                        ranked[category] = (score, profile, menu, photo)
    return [ranked[category][1:] for category in CATEGORIES]


def make_grid(path, panels):
    width, height = 500, 744 if path.stem.startswith("menus") else 540
    sheet = Image.new('RGB', (width * 3, height * ((len(panels) + 2) // 3)), '#eeeeee')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(PROJECT_ROOT / 'templates/fonts/NotoSansKR.ttf'), 21)
    for i, (label, png) in enumerate(panels):
        if png is None:
            continue
        x, y = i % 3 * width, i // 3 * height
        with Image.open(BytesIO(png)) as image:
            image.thumbnail((width - 12, height - 40))
            sheet.paste(image, (x + (width - image.width) // 2, y + 8))
        draw.text((x + 10, y + height - 30), label, fill='#202124', font=font)
    sheet.save(path)


def png_url(data):
    return 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')


def sample_menu_rows(profile, available_photos):
    category = CATEGORIES.get(business_category(profile.business_type))
    if category is None:
        return [menu.model_dump() for menu in profile.menus]
    rows = []
    used_photos = set()
    for menu in profile.menus:
        row = menu.model_dump()
        normalized = menu.name.replace('라떼', '라테').replace('연어롤', '연어 롤')
        for stem, photo in available_photos.items():
            if (stem not in used_photos and stem.startswith(category + '_')
                    and PHOTO_MENUS[category][int(stem.split('_')[1]) - 1] in normalized):
                row['photo_url'] = png_url(compose_original(photo).png)
                used_photos.add(stem)
                break
        rows.append(row)
    return rows


def sample_composition(profile, photo):
    category = CATEGORIES[business_category(profile.business_type)]
    backgrounds = sorted((PROJECT_ROOT / 'experiments/image_background').glob(f'{category}_*.png'))
    data = next((png for png in (path.read_bytes() for path in backgrounds)
                 if png.startswith(b'\x89PNG\r\n\x1a\n') and empty_background(png)), None)
    try:
        cutout = create_cutout(photo)
    except CutoutUnavailable:
        return None
    if cutout['suggest_original']:
        return None
    original = png_url(compose_original(photo).png)
    if data is None:
        return {'photo_url': original, 'cutout_url': 'data:image/png;base64,' + cutout['cutout_png_base64']}
    composed = compose_cutout(base64.b64decode(cutout['cutout_png_base64']), data)
    return {'cutout_url': 'data:image/png;base64,' + cutout['cutout_png_base64'], 'photo_url': png_url(composed.png), 'food_mask_url': png_url(composed.food_mask_png),
            'background_url': png_url(data)}


def photo_grid_shop(available_photos):
    profile = ShopProfile(shop_name='삼색 한식 샘플', business_type='한식', menus=[
        {'name': '된장찌개'}, {'name': '불고기'}, {'name': '김치찌개'},
    ])
    photo = next(data for stem, data in available_photos.items() if stem.startswith('korean_01_'))
    return profile, profile.menus[0], photo


def write_distribution(output):
    with (output / "candidates.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    designs = [json.loads(row["design_json"]) for row in rows]
    distributions = {field: Counter(item[field] for item in designs)
                     for field in ("style", "palette", "font", "ad_layout", "menu_layout")}
    for field in ("rendered_ad_layout", "rendered_menu_layout"):
        distributions[field] = Counter(row[field] for row in rows)
    with (output / "distribution.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(("field", "value", "count"))
        for field, counts in distributions.items():
            writer.writerows((field, value, count) for value, count in sorted(counts.items()))
    return distributions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--offline', action='store_true', help='Use deterministic fallback candidates.')
    mode.add_argument('--live', action='store_true', help='One recommendation and one copy request per shop.')
    mode.add_argument('--replay-live', action='store_true', help='Render successful saved live candidates without API calls.')
    parser.add_argument('--shop', help='Refresh only this shop in an existing live grid.')
    args = parser.parse_args()
    if args.shop and not args.live:
        parser.error('--shop requires --live')
    key = OPENAI_API_KEY if LLM_PROVIDER == 'openai' else GEMINI_API_KEY
    if args.live and not key.strip():
        parser.error(f'--live requires {LLM_PROVIDER.upper()}_API_KEY')
    output = PROJECT_ROOT / 'experiments/design_samples' / ('live' if args.live or args.replay_live else 'offline')
    output.mkdir(parents=True, exist_ok=True)
    ad_panels, board_panels, rows = [], [], []
    available_photos = dict(photos())
    latte = (PROJECT_ROOT / 'data/sample_assets/latte.png').read_bytes()
    available_photos = {stem: latte if stem.startswith('cafe_01') else photo
                        for stem, photo in available_photos.items()}
    saved_rows = []
    if args.replay_live or args.shop:
        with (output / 'candidates.csv').open(encoding='utf-8-sig', newline='') as file:
            saved_rows = list(csv.DictReader(file))
    with open_browser() as browser:
        shops = sample_shops(available_photos)
        if not args.shop and (not args.replay_live or any(row['shop'] == '삼색 한식 샘플' for row in saved_rows)):
            shops.append(photo_grid_shop(available_photos))
        if not args.shop and (not args.replay_live or any(row['shop'] == '골목분식 샘플' for row in saved_rows)):
            snack = ShopProfile(shop_name='골목분식 샘플', business_type='분식', menus=[
                {'name': '떡볶이', 'price': '4,000원'}, {'name': '김밥', 'price': '3,500원'},
                {'name': '튀김', 'price': '3,000원'},
            ])
            shops.append((snack, snack.menus[0], None))
        if args.shop and not any(profile.shop_name == args.shop for profile, _, _ in shops):
            parser.error(f'Unknown sample shop: {args.shop}')
        for profile, menu, photo in shops:
            composition = sample_composition(profile, photo) if photo else None
            menu_rows = sample_menu_rows(profile, available_photos)
            live_shop = args.live and (not args.shop or profile.shop_name == args.shop)
            recommend = suggest_concepts if live_shop else fallback_suggestions
            generated = None
            if args.replay_live or (args.shop and not live_shop):
                saved = [row for row in saved_rows if row['shop'] == profile.shop_name and row['menu'] == menu.name]
                if not saved:
                    raise ValueError(f'No saved candidates for {profile.shop_name}: {menu.name}')
                result = SimpleNamespace(source=saved[0]['source'], candidates=[
                    SimpleNamespace(design=DesignCandidate(**json.loads(row['design_json']), reason=row['reason']))
                    for row in saved
                ])
                copy = {'body': saved[0]['body']}
            else:
                result = recommend(profile, menu.name, suggest_original=composition is None,
                                   photo_menu_count=sum(bool(row.get('photo_url')) for row in menu_rows),
                                   **({'raise_on_error': True} if live_shop else {}))
                generated = None
                if live_shop:
                    try:
                        generated = generate_mode_copy(profile, CopyMenu(**menu.model_dump()), mode='menu', retry=False)
                    except CopyGenerationError as exc:
                        raise exc.__cause__ or exc
                copy = ad_copy(generated.model_dump() if generated else {})
            photo_url = png_url(compose_original(photo).png) if photo else None
            for index, candidate in enumerate(result.candidates, 1):
                design = candidate.design
                label = f'{profile.shop_name} · {index} {design.style} / {design.ad_layout}'
                if design.ad_layout == 'cutout_studio' and composition is None:
                    design = design.model_copy(update={'ad_layout': 'photo_full'})
                images = ({**composition, 'photo_url': photo_url}
                          if composition and design.ad_layout in ('cutout_studio', 'receipt', 'big_price')
                          else {'photo_url': photo_url})
                ad = render_ad_card(profile, menu, {**copy, **images}, design=design, browser=browser) if photo else None
                board = render_menu_board(profile, menu_rows, design=design, browser=browser)
                if ad is not None:
                    ad_panels.append((label, ad.png))
                rendered_menu_layout = menu_board_layout(design.menu_layout, menu_rows)
                board_panels.append((f"{profile.shop_name} · {index} {design.style} / {rendered_menu_layout}", board.png))
                rows.append(dict(shop=profile.shop_name, business_type=profile.business_type,
                                 menu=menu.name, candidate=index, source=result.source,
                                 copy_source=(saved[0]['copy_source'] if args.replay_live or (args.shop and not live_shop)
                                              else {'openai': 'OpenAI', 'gemini': 'Gemini'}[LLM_PROVIDER] if copy['body'] else '없음'),
                                 body=copy['body'],
                                 design_json=design.model_dump_json(exclude={'reason'}),
                                 reason=design.reason, ad_status='렌더 완료' if ad else '사진 없음', rendered_ad_layout=('사진 없음' if ad is None else 'photo_full' if design.ad_layout == 'cutout_studio' and '그릇 전체가 나오게 찍어 주세요' in ad.warnings else design.ad_layout),
                                 rendered_menu_layout=rendered_menu_layout,
                                 repeat_issues=sum(issue.startswith('consecutive_repeat:') for issue in (generated.regeneration.initial_violations + generated.regeneration.retry_violations)) if generated else 0,
                                 warnings=' | '.join((ad.warnings if ad else []) + board.warnings)))
            while len(ad_panels) % 3:
                ad_panels.append(('', None))
                board_panels.append(('', None))
            print(profile.shop_name, result.source, flush=True)
    make_grid(output / 'ads_grid.png', ad_panels)
    make_grid(output / 'menus_grid.png', board_panels)
    with (output / 'candidates.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_distribution(output)


if __name__ == '__main__':
    main()
